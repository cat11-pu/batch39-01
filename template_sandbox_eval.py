class TemplateError(ValueError):
    def __init__(self, code, name=None):
        super().__init__(code)
        self.code = code
        self.name = name


class TemplateSandbox:
    def __init__(self, allowed_fields=(), undefined="error", max_length=256, max_depth=8, max_loops=100):
        pass

    def render(self, template, context):
        raise NotImplementedError
