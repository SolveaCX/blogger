# Blogger MCP 接入

Blogger 后端提供 Streamable HTTP 端点 `https://<blogger-api-host>/api/mcp`，支持文章查询、Markdown 导入草稿和本人草稿修改。MCP 和 REST API 使用同一把 `blog_sk_` Access Key。

## 创建与撤销 Access Key

在 Blogger 后台打开 **Access Keys**，填写名称并选择访问范围。

- **继承账户权限**适用于现有 REST API 和 CLI 工作流，也可以连接 MCP。已有 Access Key 可以直接使用。
- **选定站点**适用于协作。MCP 只允许查询该站已发布文章、创建和编辑本人未发布的草稿。REST API 可通过 `/api/integration/sites` 和该站的 integration 接口读取已发布内容。

创建后复制完整密钥并保存在密码管理器中。在同一页面撤销密钥后，MCP 和 REST 请求都会失效。持有旧版专用 MCP 凭证的用户需要在 Access Keys 页面签发统一密钥。

## Claude Code 接入

在 Claude Code 使用的终端设置 `BLOGGER_MCP_URL` 为部署后的地址，通过密码管理器或安全的环境变量管理方式将 Access Key 注入 `BLOGGER_ACCESS_KEY`。在工作目录执行下面的命令。单引号让环境变量引用原样写入配置，实际值在客户端读取配置时展开。

```bash
claude mcp add-json --scope local blogger-blog '{"type":"http","url":"${BLOGGER_MCP_URL}","headers":{"Authorization":"Bearer ${BLOGGER_ACCESS_KEY}"}}'
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

## 部署验证

使用现有 schema 初始化流程为 `access_keys` 增加可选的 `site_id`。关闭自动建表的环境需先应用该字段迁移。确认 HTTPS 网关转发 `/api/mcp` 和 `Authorization` 请求头。

用测试 Access Key 验证站点范围、本人草稿编辑和版本冲突。撤销测试 Key 后，重新验证 MCP 和 REST 均拒绝它。发布及旧文修订继续走 Blogger 后台的审核流程。

参考 [Claude Code MCP 配置](https://code.claude.com/docs/en/mcp)。
