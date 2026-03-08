# 6208 Bearing Streamlit App

这是一个把 6208 轴承机电联合仿真脚本封装成网页的示例项目，适合部署到 Streamlit Community Cloud，并通过手机浏览器访问。

## 本地运行

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 启动网页：

```bash
streamlit run app.py
```

3. 浏览器打开本地地址，手机和电脑都可以访问。

## 项目结构

- `bearing_model.py`: 计算核心
- `app.py`: Streamlit 网页界面
- `Gemini3.1_Capacity_6208_v3.py`: 保留命令行入口

## 上传到 GitHub

```bash
git init
git add .
git commit -m "Initial Streamlit bearing calculator"
git branch -M main
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

## 部署到 Streamlit Community Cloud

1. 登录 [Streamlit Community Cloud](https://share.streamlit.io/)
2. 连接 GitHub 仓库
3. 选择仓库和分支
4. Main file path 填 `app.py`
5. 点击 Deploy

部署完成后会得到一个网页链接，手机浏览器直接打开即可运行。
