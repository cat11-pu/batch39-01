"""Safe quoting/unquoting of argument vectors for POSIX shell command lines.

No argument content is ever trusted to be "mostly safe": every argument is
wrapped in single quotes, so shell metacharacters (``;``, ``|``, ``&``,
``$``, backticks, globs, ...) cannot be interpreted by the shell. The only
character that needs escaping inside single quotes is the single quote
itself, handled with the standard ``'\\''`` sequence. NUL bytes cannot be
represented in a command line and are always rejected.
"""


class SinkArgError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_IFS_WHITESPACE = frozenset(" \t\n")


class SinkArgQuoter:
    @staticmethod
    def quote(argv):
        """Render an argument list as one safe POSIX shell command line.

        Each argument is individually wrapped in single quotes and internal
        single quotes are escaped as ``'\\''``. Empty strings become ``''``
        so their positions in the argument vector are preserved. A leading
        ``-`` or ``=`` needs no special handling because the value is always
        quoted; option terminators (``--``) are the caller's responsibility.

        Newlines and other control characters (except NUL) stay literal
        inside the single quotes, where the shell treats them as ordinary
        data rather than command syntax. NUL bytes raise
        :class:`SinkArgError`.
        """
        if isinstance(argv, (str, bytes)) or not hasattr(argv, "__iter__"):
            raise TypeError("argv must be an iterable of str")
        words = []
        for arg in argv:
            if not isinstance(arg, str):
                raise TypeError(
                    "every argument must be str, got %s" % type(arg).__name__
                )
            if "\x00" in arg:
                raise SinkArgError("nul_byte_not_allowed")
            words.append("'" + arg.replace("'", "'\\''") + "'")
        return " ".join(words)

    @staticmethod
    def parse(command):
        """Split a shell command line back into its original argument list.

        This is a purely static parser: no variable expansion, command
        substitution or globbing is performed, so ``$``, backticks and
        wildcards remain literal. Single quotes, double quotes and backslash
        escapes are honoured, and quoted empty strings (``''``) produce
        empty arguments instead of disappearing.

        Malformed input -- NUL bytes, unmatched quotes or a dangling
        backslash -- raises :class:`SinkArgError`.
        """
        if not isinstance(command, str):
            raise TypeError("command must be str")
        if "\x00" in command:
            raise SinkArgError("nul_byte_not_allowed")

        argv = []
        token = None
        i = 0
        length = len(command)

        while i < length:
            ch = command[i]

            if ch in _IFS_WHITESPACE:
                if token is not None:
                    argv.append(token)
                    token = None
                i += 1
                continue

            if token is None:
                token = ""

            if ch == "'":
                # Inside single quotes every character is literal,
                # including backslashes; only the closing quote ends it.
                i += 1
                begin = i
                while i < length and command[i] != "'":
                    i += 1
                if i >= length:
                    raise SinkArgError("unterminated_single_quote")
                token += command[begin:i]
                i += 1

            elif ch == '"':
                i += 1
                closed = False
                while i < length:
                    quoted_char = command[i]
                    if quoted_char == '"':
                        closed = True
                        i += 1
                        break
                    if quoted_char == "\\":
                        if i + 1 >= length:
                            raise SinkArgError("dangling_backslash")
                        next_char = command[i + 1]
                        if next_char in ('$', '`', '"', "\\", "\n"):
                            token += next_char
                        else:
                            token += quoted_char + next_char
                        i += 2
                        continue
                    token += quoted_char
                    i += 1
                if not closed:
                    raise SinkArgError("unterminated_double_quote")

            elif ch == "\\":
                if i + 1 >= length:
                    raise SinkArgError("dangling_backslash")
                next_char = command[i + 1]
                # Backslash-newline is line continuation and is removed.
                if next_char != "\n":
                    token += next_char
                i += 2

            else:
                token += ch
                i += 1

        if token is not None:
            argv.append(token)
        return argv
