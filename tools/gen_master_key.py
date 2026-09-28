"""生成加密用户密钥所需的主密钥（SECRET_MASTER_KEY）。

用法：
    python tools/gen_master_key.py

它会打印一个新的主密钥。请：
  1. 把它写进项目根目录的 .env：SECRET_MASTER_KEY=<打印出来的值>
  2. **离线备份一份**（密码管理器 / 纸质记录都行）

⚠️ 主密钥丢失 = 已保存的所有用户密钥永久无法解密，用户必须重填。
⚠️ 主密钥泄露 = 拖库者可以解开所有人的密钥。
   所以它绝不能进 git、不能进数据库、不能出现在日志里。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.crypto import generate_master_key  # noqa: E402


def main() -> None:
    key = generate_master_key()
    print("=" * 64)
    print("新的 SECRET_MASTER_KEY：")
    print()
    print(f"SECRET_MASTER_KEY={key}")
    print()
    print("=" * 64)
    print("下一步：")
    print("  1. 把上面那一行加进项目根目录的 .env")
    print("  2. 离线备份这个值（丢了就永久解不开已保存的用户密钥）")
    print("  3. 重启服务使配置生效")


if __name__ == "__main__":
    main()
