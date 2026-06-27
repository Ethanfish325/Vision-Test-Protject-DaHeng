# Git 推送计划

## 目标
将项目 [`VisionTest2.0`](..) 推送到远程仓库 `https://github.com/Ethanfish325/Vision-Test-Protject-DaHeng`

## 步骤

### 1. 更新 `.gitignore`
在现有 `.gitignore` 末尾添加一行 `*.dll`，忽略根目录下的三个DLL文件（`DxImageProc.dll`、`GxIAPI.dll`、`MCDLL_NET.dll`），因为它们体积较大不适合Git追踪。

### 2. 初始化Git提交
```bash
git add .
git commit -m "Initial commit: VisionTest2.0 project"
```

### 3. 添加远程仓库
```bash
git remote add origin https://github.com/Ethanfish325/Vision-Test-Protject-DaHeng
```

### 4. 推送到远程仓库
```bash
git branch -M main
git push -u origin main
```

### 5. 验证推送结果
```bash
git log --oneline
git remote -v
```

## 注意事项
- DLL文件（`*.dll`）会被 `.gitignore` 忽略，不会上传到仓库
- 其他所有文件（包括 `main.spec`、`cleanup_after_build.bat`、`model/` 图片、`data/users.json` 等）都会被追踪并推送
- 如果远程仓库已有内容，可能需要先 `git pull origin main --allow-unrelated-histories` 合并
