# 矿端公开核验台（GitHub Pages）

多金属（Cu / Al / Pb·Zn / Ni / Sn / Li / Fe）矿端供给的公开核验单页。**数据内联在 HTML 里**，浏览器直接打开即可，无后端、无构建。

- 线上地址：<https://xinyuzhao526-arch.github.io/PaiPaiMetals/>
- 主入口：`index.html`（与 `metals-atlas-unified.html` 内容相同）
- 自动更新说明：`docs/自动更新说明.md`
- 来源登记：`docs/*-source-registry.md`
- 默认底图：Esri World Street（需能访问外网瓦片）

> 本页是自建的公开源核验台，**不是**任何商业数据终端的镜像，也不是实时行情终端。

---

## 一、页面结构

| 区块 | 内容 |
|---|---|
| 总览 | 品种切换、样本榜（每品种 35 档）、近期供给事件 |
| 世界地图 | 圆点**只有单点资产**按实物吨位缩放；国家 / 企业 / 基准 / 库存 / 平衡项一律等大空心点。标题栏可切换「按产量 / 统一」与底图 |
| 供给事件 | 页内核验事件 + 自动抓取事件池（蓝底=自动发布，黄底=待确认） |
| 库存与显性供给 | LME / SHFE 自动刷新；GFEX（锂）与 DCE（铁）为人工核验基线 |
| 产量追踪 | 三档视图：**单点资产** / **区域** / **总量与格局** |
| 来源总表 | 逐字段口径与采用值 |

## 二、数据自动更新（GitHub Actions）

- 工作流：`.github/workflows/update-stocks.yml`，每交易日 **08:30（北京时间）** 执行，也可手动触发
- 产物：`data/stocks.json`（交易所库存）、`data/events.json`（供给事件池）
- 页面打开时**同源读取**这两个文件：读到就用实时值覆盖页内基线，读不到就保留基线，不影响其余功能
- **未覆盖**：GFEX 与 DCE 官网对自动化请求有反爬（JS 挑战 / HTTP 412），其仓单目前是页内人工核验基线

## 三、口径纪律（改数据前必读）

- 榜单 / 产量追踪 / 来源总表 / 供给事件是**人工核验的快照**，不随 Actions 更新；改动研究内容后须同步 bump `index.html` 里的 `DATA_BASELINE`
- 产量追踪分四层：**单点资产 / 企业合计 / 国家·地区 / 全球总量**。层级之间**不可相加**（企业已含其下属项目、国家是全球的一部分）
- 基别不同**不可折算**（LCE / SC6 / 镍锍 / NPI / 可用矿 等）
- 详见 `docs/自动更新说明.md`

## 四、更新与发布

1. 改本地 `metals-atlas-unified.html`
2. 同步覆盖 `github-pages/` 下的 `index.html` 与 `metals-atlas-unified.html`
3. 推送到 `xinyuzhao526-arch/PaiPaiMetals` 的 `main`
   - **不要覆盖 `data/stocks.json`**：它由 Actions 自动更新，线上版本通常比本地新
4. 等 Pages 重新构建（几十秒到几分钟），刷新页面核对

## 五、分享

```text
https://xinyuzhao526-arch.github.io/PaiPaiMetals/
https://xinyuzhao526-arch.github.io/PaiPaiMetals/?metal=Ni
https://xinyuzhao526-arch.github.io/PaiPaiMetals/?metal=Li
https://xinyuzhao526-arch.github.io/PaiPaiMetals/?metal=Fe
```

对方**不需要** GitHub / PaiWork 账号。

## 六、注意

| 点 | 说明 |
|---|---|
| 公开仓库 | 页面与内联数据对全网可见，勿写入未公开研报、持仓、密钥 |
| 地图 | 依赖 Esri 公网瓦片；公司内网若屏蔽外网，地图可能空白，表格仍可用 |
| 企业合规 | 上传前确认是否允许把业务静态页放到公有 GitHub；可用公司自建 Git / 内网 Pages 替代 |

---

<details>
<summary><b>附：把本目录部署到一个全新仓库（首次发布流程）</b></summary>

1. 登录 GitHub → **New repository** → 命名（如 `PaiPaiMetals`）→ 选 **Public** → 不要勾 README
2. 上传本目录文件（至少 `index.html`；建议整包：`index.html`、`metals-atlas-unified.html`、`docs/`、`README.md`）
3. **Settings → Pages → Build and deployment → Deploy from a branch** → Branch `main` + 文件夹 `/ (root)` → Save
4. 等 1–3 分钟，得到 `https://<用户名>.github.io/<仓库名>/`

命令行方式：

```bash
git init
git add .
git commit -m "Add verification desk"
git branch -M main
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main
```

</details>
