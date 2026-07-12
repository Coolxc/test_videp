# 第一步：Markdown → storyboard 骨架 → image prompt，然后暂停
python3 scripts/make_video.py --input script.md --mode video_first

# 用户去外部平台生成图片，放入 output/{topic}/images/

# 第二步：继续（Vision 检测 bbox → 路径提取 → 渲染）
python3 scripts/make_video.py --input output/untitled-20260712/script.md --mode video_first --skip-prompts
