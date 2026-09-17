# Sanvist Dify Stream 0.3.4

独立调用目标 Dify 对话应用，不复用 Sanvist Python 业务事件协议。

插件包含两个输入契约不同、但共用标准 Dify Service API 协议的工具：

- “调用 Dify 运营助手”：调用标准 Dify `/v1/chat-messages`。
- “调用 Dify 作业指导”：调用标准 Dify `/v1/chat-messages`。

## 输出协议

工作流和节点进度通过 `response_stream` 输出为扁平 SANVIST 帧：

```text
<SANVIST>{"stage":"node_started","phase":"started","message":"查询事实数据正在执行","dify_event":"node_started","conversation_id":"..."}</SANVIST>
```

不存在外层 `{"event":"status","data":...}`。目标 Dify 的回答正文、报表和 ECharts
按原始增量直接写入同一个 `response_stream`，不转换成 Python 事件。

## Provider 配置

- `dify_base_url`：`https://dify-sanvist.etripon.com`
- `dify_api_key`：目标 Dify 应用自己的 Service API Key。可填写 `app-...`；如果误带
  `Bearer ` 前缀，插件会自动去除，避免重复生成 `Bearer Bearer ...`。

插件只保留这一组授权字段。请在 Dify 中为同一个插件分别创建“运营助手”和
“作业指导助手”两套授权，每套填写目标应用的 URL 和 Service API Key。两个应用在
同一 Dify 实例时 URL 可以相同，API Key 用于区分目标应用。节点需要选择对应授权。

## 主工作流绑定

将 Dify 分支原来的工具节点替换为本插件的“调用 Dify 运营助手”：

- 绑定 `sys.query`、`user_id`、`role_id`、`device_list`、`reference_time`、`language`。
- 0.3.2 起新增可选入参 `channel`（`vehicle` / `app` / `pc`）：绑定后原样转发给目标
  应用的 `channel` 输入；留空或非法值时不发送该字段，目标应用未声明 `channel` 也
  不受影响。
- 首轮 `conversation_id` 留空；后续绑定上一轮的 `target_conversation_id`。
- 回复节点选择 `response_stream`，即可同时收到扁平 SANVIST 进度和原始 Dify 回答。
- 仅需纯回答时选择 `answer_stream`。

作业指导分支使用“调用 Dify 作业指导”节点，绑定 `sys.query`、`user_id`、
`device_model`、`operator_role`、`inspection_image` 和该目标应用自己的
`conversation_id`。`operator_role` 是与 `user_id`、`device_model` 相同的字符串配置项，
应直接绑定开始节点的 `operator_role`；插件不再提供中文下拉选项，并将
`novice_operator` 或 `skilled_operator` 英文值原样透传。其中 `inspection_image` 绑定开始节点的单文件图片变量；插件会把
Dify 文件对象转换成目标作业指导应用自定义输入所需的 `remote_url` 文件描述，不会
跨应用复用 `upload_file_id`。在 DSL 中应使用文件变量直接引用
`["100", "inspection_image"]`，不要把文件转换成 `{{#100.inspection_image#}}`
字符串。首轮会话 ID 留空，下一轮传回该工具输出的
`target_conversation_id`；回复节点选择 `response_stream`。
