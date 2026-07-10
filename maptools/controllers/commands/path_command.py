class PathSnapshotCommand:
    """
    全量快照模式的覆盖路径 Undo/Redo 命令。
    保存操作前后的节点列表副本，执行时直接替换。
    """
    def __init__(self, manager, old_nodes, new_nodes, refresh_cb=None):
        """
        Args:
            manager: CoveragePathManager 实例
            old_nodes: 操作前的 CoveragePathNode 列表副本 (deep copy)
            new_nodes: 操作后的 CoveragePathNode 列表副本 (deep copy)
            refresh_cb: 界面刷新回调
        """
        self.manager = manager
        self.old_nodes = old_nodes
        self.new_nodes = new_nodes
        self.refresh_cb = refresh_cb
        self._is_first_execute = True

    def execute(self):
        if self._is_first_execute:
            self._is_first_execute = False
            return
        self._apply_nodes(self.new_nodes)

    def undo(self):
        self._apply_nodes(self.old_nodes)

    def _apply_nodes(self, nodes):
        # 必须是副本，防止修改污染快照
        self.manager.set_nodes([n.duplicate() for n in nodes])
        self.manager.is_dirty = True
        
        if self.refresh_cb:
            self.refresh_cb()
