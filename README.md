# 6208 Bearing Render App

这是一个把 6208 轴承机电联合仿真脚本封装成普通网页的示例项目，适合部署到 GitHub + Render，并通过手机浏览器直接访问。当前版本同时计算油膜电容、基于 EHL 油膜剪切的摩擦力矩，以及基于油品黏温曲线的 `ν(T)`、`κ` 和 `λ`。

## 本地运行

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 启动网页：

```bash
python3 app.py
```

3. 浏览器打开 `http://127.0.0.1:5000`，手机和电脑都可以访问。

## 项目结构

- `bearing_model.py`: 计算核心，包含载荷分布、Hamrock-Dowson 膜厚、ASTM D341 黏度换算、κ/λ、电容和 EHL 摩擦力矩
- `app.py`: Flask 网页入口
- `templates/index.html`: 页面模板
- `static/styles.css`: 页面样式
- `render.yaml`: Render 部署配置
- `Gemini3.1_Capacity_6208_v3.py`: 保留命令行入口

## 部署到 Render

1. 登录 [Render](https://render.com/)
2. 选择 `New +` -> `Blueprint`
3. 连接 GitHub 仓库 `yeluofengqiao/bearing-cal`
4. Render 会自动识别仓库中的 `render.yaml`
5. 确认后点击创建服务

部署完成后会得到一个网页链接，手机浏览器直接打开即可运行。
