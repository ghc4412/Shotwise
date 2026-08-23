# MediaAsset 只建立索引，Creative Board 不拥有业务数据

Status: accepted

MediaAsset 为现有图片、视频、音频和新生成媒体建立统一身份与索引，但不移动、重命名或重新编码物理文件。Creative Board 只保存展示关系、坐标和分组；删除 Creative Board 只能删除该组织视图及其关系，不得级联删除文稿、实体、MediaAsset、物理媒体或 WorkflowRun。

## Consequences

- 旧媒体可以在不迁移文件的情况下进入媒体库和新的创作流程。
- 媒体文件位置由 MediaAsset 引用，画布布局由 Creative Board 管理，两者职责分离。
- 清理媒体或运行记录必须经过各自拥有者的明确生命周期操作，不能借用画布删除完成。
