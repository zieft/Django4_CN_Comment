import pymysql

# 链接MySQL
conn = pymysql.connect(host="local.host", port=3306, user="root", password="password", charset="utf8")
cursor = conn.cursor()

# 发送指令
cursor.execute("数据库指令")

# 获取指令结果
res = cursor.fetchall()
print(res)

