# 智慧BNCT治疗规划平台

## 一键启动（无需配置环境）

只需安装 **Docker Desktop**，然后运行一条命令即可。

### 第一步：安装 Docker Desktop

前往 [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/) 下载并安装，安装后启动它。

### 第二步：启动项目

在项目根目录（含 `docker-compose.yml` 的文件夹）打开终端，执行：

```bash
docker compose up --build
```

首次运行需要几分钟（下载依赖、编译前端），之后再启动会很快。

### 第三步：打开网页

浏览器访问：**http://localhost:3000**

### 停止服务

```bash
docker compose down
```

---

## 常见问题

**Q: 提示"docker compose"命令不存在？**  
A: 旧版 Docker 使用 `docker-compose`（带连字符），请改用：`docker-compose up --build`

**Q: 端口 3000 被占用？**  
A: 修改 `docker-compose.yml` 中 `ports` 的第一个数字，例如改为 `"8080:3000"`，然后访问 http://localhost:8080

**Q: 数据会不会丢失？**  
A: 上传的文件和计算结果保存在 Docker 数据卷中，`docker compose down` 不会删除数据。若要彻底清除，使用 `docker compose down -v`。
