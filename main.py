import uvicorn
#uvicorn是一个ASGI服务器
#uvicorn 负责“监听端口、接收网络请求、把请求交给 FastAPI”。

if __name__ == "__main__":
#为保护写法，只有直接运行 python main.py 时，下面那段才执行。
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=True)
    #server.app:app 指向server/app.py 这个文件。
    #host="127.0.0.1"只监听本机，如换成 0.0.0.0，局域网内别的设备也能访问。
    #port=8000：端口号。浏览器访问 http://127.0.0.1:8000
    
#Remove-Item data\events.json 后台数据清除