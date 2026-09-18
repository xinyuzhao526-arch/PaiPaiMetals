# 矿端公开核验台（GitHub Pages）

静态单页：铜 / 铝 / 铅锌 / 镍 / 锡 / 锂 / 铁。数据已内联，浏览器直接打开即可。

- 主入口：`index.html`（与 `metals-atlas-unified.html` 相同）
- 来源登记：`docs/*-source-registry.md`
- 默认底图：Esri World Street（需访问外网瓦片）

本页为公开源核验样本，**不是** MetalsGoWhere 产品，亦非实时行情终端。

---

## 一、首次发布（约 5–10 分钟）

### 1. 注册/登录 GitHub
打开 [https://github.com](https://github.com)，登录账号。

### 2. 新建仓库
1. 右上角 **+** → **New repository**
2. Repository name 例如：`metals-atlas`（可自定）
3. 选 **Public**（免费 Pages 最省事）或 **Private**（Private 的 Pages 通常需要付费计划，以 GitHub 当前政策为准）
4. **不要**勾选 “Add a README”（本地已有文件时更省事）
5. Create repository

### 3. 上传本目录文件
任选一种：

#### 方式 A：网页上传（零命令行）
1. 打开空仓库页面 → **uploading an existing file**
2. 把本文件夹内文件拖进去（至少 `index.html`；建议整包：`index.html`、`metals-atlas-*.html`、`docs/`、`README.md`）
3. Commit changes

#### 方式 B：Git 命令行
在本机进入已下载的 `github-pages` 目录后：

```bash
git init
git add .
git commit -m "Add metals atlas static site"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

### 4. 打开 GitHub Pages
1. 仓库页 → **Settings** → 左侧 **Pages**
2. **Build and deployment** → Source 选 **Deploy from a branch**
3. Branch 选 **main**，文件夹选 **/ (root)**
4. Save
5. 等 1–3 分钟，页面上方会出现访问地址，形如：

```text
https://<你的用户名>.github.io/<仓库名>/
```

同事用浏览器打开该链接即可（侧栏切换品种；也可用 `?metal=Fe` 等）。

---

## 二、更新数据后再发布

1. 在 PaiWork 左侧更新 `metals-atlas-unified.html` 后，再复制覆盖本目录的 `index.html` 与 `metals-atlas-unified.html`
2. 推送到 GitHub：

```bash
git add .
git commit -m "Update metals atlas data"
git push
```

或网页端再次上传覆盖 `index.html`。

Pages 一般几十秒到几分钟后自动刷新。

---

## 三、分享给同事

把下面任一链接发对方即可：

```text
https://<你的用户名>.github.io/<仓库名>/
https://<你的用户名>.github.io/<仓库名>/?metal=Ni
https://<你的用户名>.github.io/<仓库名>/?metal=Li
https://<你的用户名>.github.io/<仓库名>/?metal=Fe
```

对方**不必**有 GitHub / PaiWork 账号。

---

## 四、注意

| 点 | 说明 |
|----|------|
| 公开仓库 | 页面与内联数据对全网可见，勿写入未公开研报、持仓、密钥 |
| 地图 | 依赖 Esri/Carto 等公网瓦片；公司内网若屏蔽外网，地图可能空白，表格仍可用 |
| 企业合规 | 上传前确认是否允许将业务静态页放到公有 GitHub；可用公司自建 Git / 内网 Pages 替代 |
| 自定义域名 | Pages 设置里可绑 `atlas.example.com`（需解析 CNAME） |

---

## 五、最小文件清单

```text
github-pages/
  index.html                 # 必选，Pages 默认首页
  metals-atlas-unified.html  # 可选备份同名
  README.md
  docs/                      # 可选，来源登记
```
