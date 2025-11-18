# Vercel 部署配置说明

## 环境变量配置

在 Vercel 项目设置中添加以下环境变量：

### 数据库配置
- `DB_NAME`: 数据库名称（默认: examdb）
- `DB_USER`: 数据库用户名（默认: karlex）
- `DB_PASSWORD`: 数据库密码（默认: 828124@ZBL）
- `DB_HOST`: 数据库主机地址（默认: 8.154.86.53）
- `DB_PORT`: 数据库端口（默认: 5432）

### API 配置
- `API_BASE_URL`: API 基础 URL（默认: https://yunyj.linyi.net/api/read/getlog）
- `API_TOKEN`: API 认证 Token（默认: gzEx3e-ySUy3XGgzsKOZtw）

## 部署步骤

1. 将代码推送到 GitHub
2. 在 Vercel 中导入项目
3. 在项目设置中添加上述环境变量
4. 部署

## 注意事项

- Vercel 使用 serverless functions，每次请求都会重新加载应用
- 数据库连接会在每次请求时建立，确保数据库允许来自 Vercel IP 的连接
- 如果遇到 404 错误，检查 `vercel.json` 配置是否正确
- 确保 `requirements.txt` 包含所有依赖

## 文件结构

```
.
├── app.py              # Flask 主应用
├── api/
│   └── index.py       # Vercel serverless function 入口
├── templates/
│   └── index.html     # 前端模板
├── vercel.json        # Vercel 配置文件
├── requirements.txt    # Python 依赖
└── .vercelignore      # Vercel 忽略文件
```

