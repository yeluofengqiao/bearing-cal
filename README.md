# Bearing Engineering Web Tools

这是一个把多个轴承工程计算小工具封装成网页的示例项目，适合部署到 GitHub + Render，并通过手机浏览器直接访问。当前包含两个主要页面：

- `/`：通用轴承机电联合仿真，计算油膜电容、基于 EHL 油膜剪切的摩擦力矩，以及基于油品黏温曲线的 `ν(T)`、`κ` 和 `λ`
- `/tapered-preload`：圆锥滚子轴承预压垫片推荐，按“轴承刚度 + 座孔刚度 + 轴刚度 + 座孔热膨胀”给出连续厚度和离散点推荐

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
4. 如需圆锥滚子轴承预压垫片计算，进入 `http://127.0.0.1:5000/tapered-preload`。

## 项目结构

- `bearing_model.py`: 机电联合仿真计算核心，包含载荷分布、Hamrock-Dowson 膜厚、ASTM D341 黏度换算、κ/λ、电容、自动估算滑滚比和 EHL 摩擦力矩
- `tapered_preload_calculator.py`: 圆锥滚子轴承预压垫片推荐计算核心
- `app.py`: Flask 网页入口，包含两个计算页面路由
- `templates/index.html`: 页面模板
- `templates/tapered_preload.html`: 圆锥滚子轴承预压垫片页面
- `static/styles.css`: 页面样式
- `render.yaml`: Render 部署配置
- `Gemini3.1_Capacity_6208_v3.py`: 保留命令行入口

机电联合模型中，Hertz 接触使用两体约化模量 `E*`，Hamrock-Dowson 无量纲组使用其文献约定的 `2E*`；`λ` 使用最小膜厚，电容和剪切代理使用中央膜厚。摩擦力矩按总滑动耗散功率除以轴角速度闭合，绝对值仍需台架标定。

## 部署到 Render

1. 登录 [Render](https://render.com/)
2. 选择 `New +` -> `Blueprint`
3. 连接 GitHub 仓库 `yeluofengqiao/bearing-cal`
4. Render 会自动识别仓库中的 `render.yaml`
5. 确认后点击创建服务

部署完成后会得到一个网页链接，手机浏览器直接打开即可运行。
