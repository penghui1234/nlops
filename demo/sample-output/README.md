# NLOps Demo · Sample HTML Output

5 个场景的 HTML 智能诊断书示例，由 `demo/run_demo.py` 自动生成。

## 文件清单

| 文件 | 大小 | 场景 | 严重度 |
|---|---:|---|---|
| [`index.html`](index.html) | 1.4 KB | 索引页 | — |
| [`health_check-demo-1.html`](health_check-demo-1.html) | 5.6 KB | 早晨巡检 | 🔵 info |
| [`troubleshoot-demo-2.html`](troubleshoot-demo-2.html) | 6.9 KB | 故障下钻 ⭐ 最复杂 | 🟠 high |
| [`execute_action-demo-3.html`](execute_action-demo-3.html) | 5.7 KB | 执行修复（Confirm Token） | 🔵 info |
| [`knowledge_query-demo-4.html`](knowledge_query-demo-4.html) | 5.8 KB | 历史方案匹配 92% | 🔵 info |
| [`alert_driven-demo-5.html`](alert_driven-demo-5.html) | 6.6 KB | 告警自动闭环 | 🔴 critical |

## 在浏览器中查看

### 选项 1：克隆仓库后本地打开

```bash
git clone https://github.com/penghui1234/nlops
cd nlops/demo/sample-output
open index.html             # macOS
xdg-open index.html         # Linux
start index.html            # Windows
```

### 选项 2：通过 GitHub Pages 在线访问

> 仓库管理员需在 **Settings → Pages → Source** 选择 `main` 分支，路径 `/`。
> 启用后访问：
> `https://penghui1234.github.io/nlops/demo/sample-output/index.html`
> （**仓库当前为 private，需要先改成 public 或者购买 GitHub Pro 启用 private repo Pages**）

### 选项 3：通过 GitHub raw 链接预览（不渲染）

GitHub 不会直接在仓库页面渲染 HTML（出于安全考虑）。
但可以通过 [HTMLPreview.github.io](https://htmlpreview.github.io/) 代理：

```
https://htmlpreview.github.io/?https://github.com/penghui1234/nlops/blob/main/demo/sample-output/index.html
```

> 注意：这种方式只对 **public** 仓库有效。

## 重新生成

这些 HTML 是一次性快照。修改场景数据 / 模板后重跑：

```bash
cd <repo>
python3 -m demo.run_demo
cp /tmp/nlops-demo/*.html demo/sample-output/
git commit -am "demo: refresh sample output"
```

## 视觉风格

- **顶部 header**：AWS 深色海军蓝 (`#232f3e`) + 白字
- **强调色**：AWS 橙色 (`#ff9900`)（badge / 分隔线）
- **卡片**：白底 + 圆角 + 浅阴影
- **风险色**：low 绿、med 橙、high 红
- **响应式**：桌面 max-width 1024px；移动端单列
- **图表**：通过 ECharts CDN 加载（如果 `metrics_chart` 字段存在）
- **字体栈**：苹果系统字体 → Helvetica Neue → 苹方 → 微软雅黑
