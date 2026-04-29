from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Tuple

import ipywidgets as widgets


@dataclass(frozen=True)
class LayoutFrame:
    layout_type: str
    owner_id: str
    slot_key: str

    @property
    def slot_id(self) -> str:
        return f"{self.layout_type}:{self.owner_id}:{self.slot_key}"


@dataclass(frozen=True)
class RenderContext:
    source_cell_id: str | None
    layout_stack: Tuple[LayoutFrame, ...]

    @property
    def render_slot_id(self) -> str | None:
        if not self.layout_stack:
            return None
        return self.layout_stack[-1].slot_id

    @property
    def layout_path(self) -> str | None:
        if not self.layout_stack:
            return None
        return "/".join(frame.slot_id for frame in self.layout_stack)


_source_cell_id_var: ContextVar[str | None] = ContextVar(
    "mercury_source_cell_id",
    default=None,
)
_layout_stack_var: ContextVar[Tuple[LayoutFrame, ...]] = ContextVar(
    "mercury_layout_stack",
    default=(),
)


def get_source_cell_id() -> str | None:
    return _source_cell_id_var.get()


def get_layout_stack() -> Tuple[LayoutFrame, ...]:
    return _layout_stack_var.get()


def get_render_context() -> RenderContext:
    return RenderContext(
        source_cell_id=get_source_cell_id(),
        layout_stack=get_layout_stack(),
    )


def _resolve_source_cell_id_from_kernel() -> str | None:
    try:
        from IPython import get_ipython
    except Exception:
        return None

    try:
        ip = get_ipython()
        kernel = getattr(ip, "kernel", None)
        if kernel is None or not hasattr(kernel, "get_parent"):
            return None

        parent = kernel.get_parent() or {}
        metadata = parent.get("metadata") or {}
        cell_id = metadata.get("cellId") or metadata.get("cell_id")
        return str(cell_id) if cell_id else None
    except Exception:
        return None


def get_effective_source_cell_id() -> str | None:
    return get_source_cell_id() or _resolve_source_cell_id_from_kernel()


def get_widget_render_metadata() -> dict[str, str]:
    ctx = get_render_context()
    source_cell_id = get_effective_source_cell_id()

    metadata: dict[str, str] = {}
    if source_cell_id is not None:
        metadata["source_cell_id"] = source_cell_id
        metadata["cell_id"] = source_cell_id
    if ctx.render_slot_id is not None:
        metadata["render_slot_id"] = ctx.render_slot_id
    if ctx.layout_path is not None:
        metadata["layout_path"] = ctx.layout_path
    return metadata


def with_widget_render_metadata(kwargs: dict) -> dict:
    merged = dict(kwargs)
    merged.update(get_widget_render_metadata())
    return merged


def apply_widget_render_metadata(widget: object) -> None:
    for key, value in get_widget_render_metadata().items():
        if hasattr(widget, key):
            setattr(widget, key, value)


@contextmanager
def source_cell_context(cell_id: str | None) -> Iterator[None]:
    token = _source_cell_id_var.set(cell_id)
    try:
        yield
    finally:
        _source_cell_id_var.reset(token)


def push_layout_frame(frame: LayoutFrame) -> Token:
    stack = _layout_stack_var.get()
    return _layout_stack_var.set(stack + (frame,))


def pop_layout_frame(token: Token) -> None:
    _layout_stack_var.reset(token)


class LayoutContextOutput(widgets.Output):
    """
    Output widget that contributes its layout slot to the Mercury render context.
    """

    def __init__(self, *args, layout_frame: LayoutFrame | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._layout_frame = layout_frame
        self._layout_tokens: list[Token] = []

    @property
    def layout_frame(self) -> LayoutFrame | None:
        return self._layout_frame

    def __enter__(self):
        if self._layout_frame is not None:
            token = push_layout_frame(self._layout_frame)
            self._layout_tokens.append(token)
        return super().__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            if self._layout_tokens:
                pop_layout_frame(self._layout_tokens.pop())
