# Blogger MCP 接入

Blogger 后端提供 Streamable HTTP 端点 `https://<blogger-api-host>/api/mcp`，支持指定站点的文章查询、Markdown 导入草稿和本人草稿修改。实际地址以部署后的验证结果为准。

## Claude Code 接入

在 Claude Code 使用的终端设置 `BLOGGER_MCP_URL` 为已开通的地址，并通过密码管理器或安全的环境变量管理方式注入 `BLOGGER_MCP_TOKEN`。在工作目录执行下面的命令。单引号让环境变量引用原样写入配置，实际值在客户端读取配置时展开。

```bash
claude mcp add-json --scope local blogger-blog '{"type":"http","url":"${BLOGGER_MCP_URL}","headers":{"Authorization":"Bearer ${BLOGGER_MCP_TOKEN}"}}'
claude mcp list
```

从同一个环境启动 Claude Code，先请它调用 `list_sites`，确认授权站点和可用的语言键。其他支持 Streamable HTTP 和自定义请求头的客户端也可使用同一地址及 `Authorization: Bearer <token>` 请求头。

## 工具及使用顺序

| 工具 | 参数与结果 |
| --- | --- |
| `list_sites` | 返回已授权站点的 `id`、名称、`slug`、站点地址和语言键。 |
| `list_posts` | 传 `site_id`。可选 `status`（`draft` 或 `published`）、`language`、`q`、`limit`、`offset`。`q` 按标题或 slug 搜索。分页默认 `20` 条、偏移 `0`，每次最多 `100` 条。返回 `items`、`total`、`limit` 和 `offset`。 |
| `get_post` | 传 `site_id` 和 `post_id`。返回正文 Markdown、渲染 HTML、状态、`updated_at` 和已存的 canonical 等字段。仅已发布文章返回 `path`。 |
| `create_draft` | 传 `site_id` 与 `post`，必填 `title`、`slug`、`language`、`markdown_content`。保存为新草稿。同站点、语言和 slug 已存在时返回冲突。 |
| `update_draft` | 传 `site_id`、`post_id`、从最新查询结果复制的 `expected_updated_at`，以及 `changes`。正文、标题和指定元数据可改，slug 和语言保持原值。 |

`post` 和 `changes` 均可包含 `excerpt`、`cover_image_url`、`meta_title`、`meta_description`。更新时省略的字段保留原值。可选元数据传 `null` 可清空。正文和标题需要实际文本。

创建草稿示例

```json
{
  "site_id": "<from list_sites>",
  "post": {
    "title": "What Is Flatkey?",
    "slug": "what-is-flatkey",
    "language": "<approved site language key>",
    "markdown_content": "# What Is Flatkey?\n\nDraft article content.",
    "meta_description": "Draft description for review."
  }
}
```

修改时先调用 `get_post`，再把最新的 `updated_at`（包含时区）传给 `expected_updated_at`。收到 `409` 时重新查询并检查其他修改后再提交。旧文修订可以用 `get_post` 读取原文，再用独立 slug 建一份草稿。把原文 URL 和草稿 ID 一并交给站点负责人，由他们审核并应用到原文。视频可先用 Markdown 链接，播放器嵌入取决于站点支持。

## 内部开通与验证

1. 确认目标站点已经接入该 Blogger 实例，并核实站点 ID。VOC.ai 需单独确认。给每位协作者配置独立的 Blogger 作者身份和凭证，负责人保留账号登录与普通管理密钥。
2. 为每位协作者生成 `blog_mcp_` 加 `secrets.token_urlsafe(32)` 的随机凭证。用密码管理器保存原值，以加密渠道交付。服务端只保存整个凭证的 SHA-256 小写十六进制摘要。
3. 在 Blogger API 的部署配置中设置 `BLOGGER_MCP_GRANTS`，按下例填入真实的数据库 ID 和摘要。空列表 `[]` 时，MCP 请求没有可用凭证。轮换或撤销时更新配置并部署到所有实例。

```json
[
  {
    "key_sha256": "<64 lowercase hexadecimal characters>",
    "user_id": "<active dedicated Blogger user ID>",
    "site_ids": ["<approved Blogger site ID>"]
  }
]
```

在部署链上保留该配置。Cloud Run 脚本的 `--set-env-vars` 与 `--set-secrets` 会重设对应配置，若走该脚本应在正式部署配置里显式注入。核对 HTTPS 入口将 `/api/mcp` 路径及 `Authorization` 请求头转到 API。现有普通 REST 注册接口会为新用户签发可跨站操作的 `operator` 账号，对外开通前须确认生产入口对自助注册有适当限制。

用测试凭证验证 `list_sites` 只返回授权站点，跨站请求被拒，已上线文章和其他作者的草稿无法修改，凭证也无法登录普通 REST 管理接口。再用明确标记的测试草稿验证创建、更新和重复提交冲突。MCP 的修改工具只接受已授权站点内、归该作者的当前草稿。发布和应用旧文修订通过原有 CMS 审核流程执行。

参考 [Claude Code MCP 配置](https://code.claude.com/docs/en/mcp)。
