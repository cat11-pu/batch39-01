"""可复核的网格绕序修复管线（只读输入、确定性输出）。"""

import copy


class MeshWindingRepair:
    def repair(self, vertices, indices, groups=None, index_bits=32):
        """运行确定性修复管线，所有输入保持只读。"""
        vertices = copy.deepcopy(vertices)
        indices = copy.deepcopy(indices)
        vertex_count = len(vertices)

        stats_before = {
            "vertices": vertex_count,
            "triangles": len(indices),
        }

        # 1. 索引位宽守卫：超宽必须显式报错，禁止静默回绕。
        max_allowed = (1 << index_bits) - 1
        if vertex_count > max_allowed + 1:
            raise ValueError(
                "vertex count %d exceeds %d-bit index capacity %d"
                % (vertex_count, index_bits, max_allowed + 1)
            )
        for triangle in indices:
            for idx in triangle:
                if idx > max_allowed:
                    raise ValueError(
                        "index %d exceeds %d-bit index range %d"
                        % (idx, index_bits, max_allowed)
                    )

        # 2. 剔除越界索引与零面积三角形。
        removed = []
        kept = []
        for tri_id, triangle in enumerate(indices):
            if not all(0 <= idx < vertex_count for idx in triangle):
                removed.append(tri_id)
                continue
            p0 = vertices[triangle[0]]["pos"]
            p1 = vertices[triangle[1]]["pos"]
            p2 = vertices[triangle[2]]["pos"]
            geometric_normal = _vec_cross(
                _vec_sub(p1, p0), _vec_sub(p2, p0)
            )
            if geometric_normal == (0.0, 0.0, 0.0):
                removed.append(tri_id)
                continue
            kept.append(
                {
                    "id": tri_id,
                    "raw": tuple(triangle),
                    "geo_normal": geometric_normal,
                }
            )
        removed_set = set(removed)

        # 3. 按 (位置, 法线, UV) 三元组焊接；仅重映射索引，顶点数组不动。
        weld_target = {}
        key_to_target = {}
        referenced_keys = set()
        referenced_old = set()
        for record in kept:
            for idx in record["raw"]:
                referenced_old.add(idx)
                vertex = vertices[idx]
                key = (
                    tuple(vertex["pos"]),
                    tuple(vertex["normal"]),
                    tuple(vertex["uv"]),
                )
                referenced_keys.add(key)
                if key not in key_to_target:
                    key_to_target[key] = idx
                weld_target[idx] = key_to_target[key]
        welded = len(referenced_old) - len(referenced_keys)

        for record in kept:
            record["tri"] = tuple(weld_target[idx] for idx in record["raw"])

        # 4. 统计每条无向边的邻接面及有向遍历方向。
        edge_faces = {}
        for record in kept:
            tri = record["tri"]
            tri_id = record["id"]
            for start, end in (
                (tri[0], tri[1]),
                (tri[1], tri[2]),
                (tri[2], tri[0]),
            ):
                edge = (start, end) if start < end else (end, start)
                forward = start < end
                edge_faces.setdefault(edge, []).append((tri_id, forward))

        non_manifold = sorted(
            edge for edge, faces in edge_faces.items() if len(faces) > 2
        )
        non_manifold_set = set(non_manifold)
        questionable = set(non_manifold_set)

        # 5. 通过流形边（恰有两个邻接面）建立连通分量。
        #    邻接只保证分量内朝向统一；整体朝向由每张面的几何法线与
        #    原始法线的点积投票决定（整体反转的网格边关系仍然自洽，
        #    邻接本身无法分辨正反）。
        parent = {record["id"]: record["id"] for record in kept}

        def find(x):
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:
                parent[x], x = root, parent[x]
            return root

        def union(a, b):
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

        manifold_edges = []
        for edge, faces in edge_faces.items():
            if len(faces) != 2:
                continue
            (face_a, forward_a), (face_b, forward_b) = faces
            union(face_a, face_b)
            manifold_edges.append((face_a, forward_a != forward_b))

        components = {}
        for record in kept:
            components.setdefault(find(record["id"]), []).append(record)

        # 邻接票：共享边反向遍历为朝向一致，同向遍历为需要翻转。
        adjacency_votes = {}
        for face_id, consistent in manifold_edges:
            votes = adjacency_votes.setdefault(find(face_id), [0, 0])
            votes[0 if consistent else 1] += 1

        # 法线票：每张面的几何法线与其顶点原始法线和的点积。
        normal_votes = {}
        for record in kept:
            reference_normal = self._original_normal_sum(
                record["tri"], vertices
            )
            alignment = _vec_dot(record["geo_normal"], reference_normal)
            votes = normal_votes.setdefault(find(record["id"]), [0, 0])
            if alignment > 0.0:
                votes[0] += 1
            elif alignment < 0.0:
                votes[1] += 1

        # 6. 先看邻接票；邻接平票或分量无邻接（孤立面）时用法线票；
        #    仍然平票则由包围盒最小的面对照原始法线拍板。
        flipped_ids = set()
        undetermined_components = set()
        for root, members in components.items():
            adj_keep, adj_flip = adjacency_votes.get(root, [0, 0])
            norm_keep, norm_flip = normal_votes.get(root, [0, 0])
            # 邻接出现内部不一致时，多数冲突边决定整体翻转；邻接自洽
            # （含整体反转）或分量无邻接时，由法线票决定绝对朝向。
            if adj_flip > adj_keep:
                keep_votes, flip_votes = adj_keep, adj_flip
            else:
                keep_votes, flip_votes = norm_keep, norm_flip
            flip_component = False
            if flip_votes > keep_votes:
                flip_component = True
            elif keep_votes > flip_votes:
                flip_component = False
            else:
                smallest = min(
                    members,
                    key=lambda record: (
                        self._bbox_diagonal_sq(record["tri"], vertices),
                        record["id"],
                    ),
                )
                reference_normal = self._original_normal_sum(
                    smallest["tri"], vertices
                )
                alignment = _vec_dot(smallest["geo_normal"], reference_normal)
                if alignment == 0.0:
                    # 原始法线整体退化（如全为占位法线）时，用包围盒最小
                    # 面相对分量包围盒中心的几何外向性裁决，确定可复核。
                    outward = self._outward_direction(
                        smallest["tri"], members, vertices
                    )
                    alignment = _vec_dot(smallest["geo_normal"], outward)
                if alignment < 0.0:
                    flip_component = True
                elif alignment > 0.0:
                    flip_component = False
                else:
                    undetermined_components.add(root)
            if flip_component:
                for record in members:
                    flipped_ids.add(record["id"])

        for record in kept:
            if record["id"] in flipped_ids:
                a, b, c = record["tri"]
                record["tri"] = (a, c, b)
                record["geo_normal"] = (
                    -record["geo_normal"][0],
                    -record["geo_normal"][1],
                    -record["geo_normal"][2],
                )

        # 无法定向的分量：其全部边列入存疑清单，不强行翻转。
        for root in undetermined_components:
            for record in components[root]:
                tri = record["tri"]
                for start, end in (
                    (tri[0], tri[1]),
                    (tri[1], tri[2]),
                    (tri[2], tri[0]),
                ):
                    questionable.add(
                        (start, end) if start < end else (end, start)
                    )

        # 7. 面积加权重算法线，并与原始法线保持同向。
        accumulated = {}
        for record in kept:
            tri = record["tri"]
            for idx in tri:
                target = accumulated.setdefault(idx, [0.0, 0.0, 0.0])
                normal = record["geo_normal"]
                target[0] += normal[0]
                target[1] += normal[1]
                target[2] += normal[2]

        normals = [tuple(vertex["normal"]) for vertex in vertices]
        for idx, geometric in accumulated.items():
            original = tuple(vertices[idx]["normal"])
            alignment = _vec_dot(geometric, original)
            if alignment < 0.0:
                geometric = [-geometric[0], -geometric[1], -geometric[2]]
            length = _vec_norm(geometric)
            if alignment == 0.0 or length == 0.0:
                normals[idx] = original
                for record in kept:
                    if idx in record["tri"]:
                        tri = record["tri"]
                        for start, end in (
                            (tri[0], tri[1]),
                            (tri[1], tri[2]),
                            (tri[2], tri[0]),
                        ):
                            questionable.add(
                                (start, end) if start < end else (end, start)
                            )
            else:
                normals[idx] = (
                    geometric[0] / length,
                    geometric[1] / length,
                    geometric[2] / length,
                )

        # 8. 材质分组稳定：整型三角形编号过滤被剔除项，其余原样保留。
        stable_groups = None
        if groups is not None:
            stable_groups = []
            for group in groups:
                if isinstance(group, (list, tuple)) and all(
                    isinstance(item, int) for item in group
                ):
                    stable_groups.append(
                        [
                            tri_id
                            for tri_id in group
                            if tri_id not in removed_set
                        ]
                    )
                else:
                    stable_groups.append(copy.deepcopy(group))

        output_indices = [record["tri"] for record in kept]
        bounds = self._bounds(kept, vertices)
        stats_after = {
            "vertices": vertex_count,
            "welded_vertices": len(referenced_keys),
            "triangles": len(kept),
            "flipped": len(flipped_ids),
            "welded": welded,
            "removed": len(removed),
            "non_manifold_edges": len(non_manifold),
            "questionable_edges": len(questionable),
            "bounds": bounds,
        }

        return {
            "vertices": copy.deepcopy(vertices),
            "indices": output_indices,
            "normals": normals,
            "groups": stable_groups,
            "removed": sorted(removed),
            "welded": welded,
            "flipped": len(flipped_ids),
            "non_manifold": [tuple(edge) for edge in non_manifold],
            "questionable": sorted(tuple(edge) for edge in questionable),
            "stats": {
                "before": stats_before,
                "after": stats_after,
                "triangles": len(kept),
                "vertices": vertex_count,
                "bounds": bounds,
            },
        }

    @staticmethod
    def _bbox_diagonal_sq(tri, vertices):
        axes = tuple(
            [vertices[idx]["pos"][axis] for idx in tri]
            for axis in range(3)
        )
        return sum(
            (max(axis_values) - min(axis_values)) ** 2
            for axis_values in axes
        )

    @staticmethod
    def _original_normal_sum(tri, vertices):
        result = [0.0, 0.0, 0.0]
        for idx in tri:
            normal = vertices[idx]["normal"]
            result[0] += normal[0]
            result[1] += normal[1]
            result[2] += normal[2]
        return tuple(result)

    @staticmethod
    def _outward_direction(tri, members, vertices):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        referenced = set()
        for record in members:
            referenced.update(record["tri"])
        for idx in referenced:
            pos = vertices[idx]["pos"]
            for axis in range(3):
                mins[axis] = min(mins[axis], pos[axis])
                maxs[axis] = max(maxs[axis], pos[axis])
        center = [(mins[axis] + maxs[axis]) / 2.0 for axis in range(3)]
        face_center = [0.0, 0.0, 0.0]
        for idx in tri:
            pos = vertices[idx]["pos"]
            face_center[0] += pos[0] / 3.0
            face_center[1] += pos[1] / 3.0
            face_center[2] += pos[2] / 3.0
        delta = [face_center[axis] - center[axis] for axis in range(3)]
        dominant = max(range(3), key=lambda axis: abs(delta[axis]))
        direction = [0.0, 0.0, 0.0]
        direction[dominant] = 1.0 if delta[dominant] >= 0.0 else -1.0
        return tuple(direction)

    @staticmethod
    def _bounds(kept, vertices):
        if not kept:
            return {"min": None, "max": None}
        referenced = set()
        for record in kept:
            referenced.update(record["tri"])
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        for idx in referenced:
            pos = vertices[idx]["pos"]
            for axis in range(3):
                mins[axis] = min(mins[axis], pos[axis])
                maxs[axis] = max(maxs[axis], pos[axis])
        return {"min": tuple(mins), "max": tuple(maxs)}


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_norm(a):
    return (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5
