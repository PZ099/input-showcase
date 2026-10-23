# INPUT

Windows 键盘、鼠标与手柄输入显示工具，适合游戏直播、Apex 身法教学和操作录制。

[网站与下载](https://pz099.github.io/input-showcase/) · [交互演示](https://pz099.github.io/input-showcase/#demo) · [模型库与图集](https://pz099.github.io/input-showcase/#models)

支持实时按键、鼠标侧键与滚轮、鼠标移动方向，以及手柄摇杆、肩键、扳机和背键反馈。直播模式可锁定窗口并穿透点击，键鼠与手柄窗口可独立移动。安装包名称为 **INPUT Setup.exe**。

内置 G502、GPW 二代、DualSense、DualSense Edge 四款默认模型，其余型号在软件内按需下载；支持“已下载”筛选、单型号删除与离线使用。云端模型发布后，软件自动检查目录更新。

网站包含 79 款鼠标、89 款手柄，按品牌和系列浏览；相近版本在系列内切换。图集还包含身法、完整作战两套键位。部分产品图为示意，详情与原图中保留标记。

网页演示仅响应页面内操作。桌面工具与模型下载是独立程序功能。

## 网站

GitHub Pages 使用 Actions 从 `main` 发布。`tools/build_site.py` 校验并装配图集资源与安装包；安装包从同源下载，保留 `INPUT Setup.exe` 文件名。静态文件位于 `dist/`。

入口为 `index.html`，模型索引为 `models.json`，图片来源说明在 `assets/atlas/sources.txt`。

首页含可直接读取的用途简介、摘要、规范地址和软件结构化数据。[站点地图](https://pz099.github.io/input-showcase/sitemap.xml)仅包含真实网页地址；IndexNow 验证文件位于项目目录。

## 素材

产品名称与商标属于各自权利人。图集沿用 INPUT 中的外观参考、轮廓及程序反馈示例；来源说明随图集保留。

## 1.0.1

修复 Windows 显示缩放下模型放大裁切与反馈错位；未下载型号的预览只保留在内存中，支持删除本地型号且不会自动恢复。设置控件与搜索框统一样式，连续滚动保留速度并平滑减速。
