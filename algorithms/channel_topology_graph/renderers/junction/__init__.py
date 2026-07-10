"""Junction 渲染内部实现子包。

职责：
    只承载 junction 领域的内部绘图与 overlay 组合实现。

边界：
    本子包不是稳定公开入口；
    外部调用方应继续走 `renderers.junction_renderers` 或包级 `renderers` 正式入口。
"""

__all__: tuple[str, ...] = ()
