# sanvist_dify_stream 0.3.6 安装包（线上原包）

从 Dify 单机 `117.72.75.33` 的 `plugin_daemon/plugin_packages/` 原样取出，即线上（2026-11-03 SGT 起）实际运行的那份包，未重新打包。
用于迁移到其他 Dify 实例：与线上及导出 DSL 里的依赖标识完全一致。

| 项 | 值 |
| --- | --- |
| 精确插件标识 | `sanvist/sanvist_dify_stream:0.3.6@08c13423400e1f581af61f64cd3f01932324eec475ce63333c390e2ad14743f0` |
| 安装包 SHA256 | `6e03d8a236eeb719a91d17938400ddb951d2387adabf634ce3c35073890aa656`（与标识后缀不是同一种校验，不互相替代） |
| 对应源码 | `sanvist_dify_stream` 提交 `08381bd` 的仓库根目录（已逐文件比对，内容一致） |
| 运行环境 | Python 3.12，依赖见包内 `requirements.txt` |

## 安装

1. Dify 控制台 → 插件 → 安装插件 → 本地插件，选本目录的 `.difypkg`。
2. 包未签名：目标实例 `.env` 需 `FORCE_VERIFYING_SIGNATURE=false`，否则拒装。
3. 安装时 plugin daemon 会联网装 Python 依赖；国内镜像偶发缺文件（404），失败先看日志里的 URL，必要时换官方 PyPI。
4. 同一插件换版本要先卸载旧版再装（本地包没有升级接口）；卸载重装会保留已建的授权。
5. 装好后建授权（provider credential），字段：`dify_base_url` `dify_api_key`。**每个子应用建一份授权**（`dify_api_key` 填该子应用的 API Key），总入口各节点选对应授权。注意导出的 DSL 不含节点的 `credential_id`，导入后要逐个节点重新选授权，否则会调错子应用。包内多带了一个无害的 `.pytest_cache/` 目录（打包时遗留），不影响运行。

> 本仓库根目录就是插件源码目录：以后打新包时要排除 `releases/`、`tests/`、`.pytest_cache/`，免得把旧安装包打进新包。
