# 多索雷斯假日 · 评论封神榜

对齐异环《评论用户统计》表：按 UID 聚合评论数排名。未完成稿（约 91%，未爬楼中楼）。

- 仓库：https://github.com/hualeide/dossoles-fengshen
- 网页：https://hualeide.github.io/dossoles-fengshen/
- 国内镜像：https://cdn.jsdelivr.net/gh/hualeide/dossoles-fengshen@main/docs/index.html
- 表（Release）：https://github.com/hualeide/dossoles-fengshen/releases
- 原视频：https://www.bilibili.com/video/BV1fy4y1L7Rq/

```text
pip install -r requirements.txt
python scrape_comments.py
python export_rank.py --parts
python build_web.py
```

不要把 `out/`、`data/` 里的 CSV/SQLite 推进仓库。
