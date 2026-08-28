# 多索雷斯假日 · 评论封神榜

对齐异环《评论用户统计》表：按 UID 聚合评论数排名。

- 视频：https://www.bilibili.com/video/BV1fy4y1L7Rq/
- B 站显示约 549 万条。Excel 单表约 104 万行上限，完整明细在 CSV。

```text
pip install -r requirements.txt
python scrape_comments.py
python export_rank.py
```

输出：`out/明日方舟_多索雷斯假日_评论用户统计.xlsx`

网页：https://hualeide.github.io/dossoles-fengshen/

源码在 `docs/`。本地预览：`python -m http.server 8766`（在 `docs/` 下）。

不要把 `out/`、`data/` 里的 CSV/SQLite 推上 GitHub。
