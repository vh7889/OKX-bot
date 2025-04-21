import asyncio
import websockets
import time
import hmac
import hashlib
import base64
import json
import random
import string
from datetime import datetime, UTC
import requests
import os

# ✅ 网格开关参数
enable_long_grid = True  # 是否启用多单网格
enable_short_grid = True  # 是否启用空单网格

# ✅ API 配置
API_KEY = ""
SECRET_KEY = ""
PASSPHRASE = ""
feishu_token = ''  # 飞书TOKEN

# ✅ 多单交易参数
long_position = 0  # 当前多单持仓
long_trigger_price = 85802.6  # 多单触发价格
long_grid_percentage = 0.6 / 100  # 多单网格间距
long_grid_size = 0.002  # 多单每次买入量
long_max_position = 0.01  # 多单最大持仓
long_take_profit_count = 0  # 多单止盈次数

# ✅ 空单交易参数
short_position = 0.008  # 当前空单持仓
short_trigger_price = 87356.7  # 空单触发价格
short_grid_percentage = 0.6 / 100  # 空单网格间距
short_grid_size = 0.002  # 空单每次卖出量
short_max_position = 0.01  # 空单最大持仓
short_take_profit_count = 0  # 空单止盈次数

# ✅ 存储订单 ID
buy_ordId = None
close_long_ordId = None
take_profit_count = 0
BASE_URL = "https://www.okx.com"


def save_order_info(order_type, order_id, price, pos_side=None):
    """保存订单信息到 JSON 文件
    order_type: 'buy' 或 'sell'
    order_id: 订单ID
    price: 委托价格
    pos_side: 持仓方向 'long' 或 'short'
    """
    filename = 'order_records.json'
    try:
        # 读取现有数据
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                data = json.load(f)
        else:
            data = {'orders': {}}

        # 添加新订单信息
        data['orders'][str(order_id)] = {
            'side': order_type,
            'price': float(price),
            'pos_side': pos_side
        }

        # 保存到文件
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)

        # print(f"✅ 已保存订单信息: ID={order_id}, 方向={order_type}, 持仓方向={pos_side}, 价格={price}")
    except Exception as e:
        print(f"❌ 保存订单信息失败: {e}")


def get_order_info(order_id):
    """从 JSON 文件中读取订单信息
    返回: (order_type, price, pos_side) 或 (None, None, None)
    """
    filename = 'order_records.json'
    try:
        if not os.path.exists(filename):
            return None, None, None

        with open(filename, 'r') as f:
            data = json.load(f)

        # 查找订单
        order_id = str(order_id)
        if order_id in data.get('orders', {}):
            order_info = data['orders'][order_id]
            return order_info['side'], order_info['price'], order_info['pos_side']

        return None, None, None
    except Exception as e:
        print(f"❌ 读取订单信息失败: {e}")
        return None, None, None


def generate_clOrdId(side):
    """生成唯一 clOrdId"""
    timestamp = str(int(time.time() * 1000))
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{side}{random_str}{timestamp[-6:]}"[:32]


def calculate_grid_prices(trigger_price, pos_side="long"):
    """计算网格价格"""
    if pos_side == "long":
        buy_price = round(trigger_price * (1 - long_grid_percentage), 2)
        close_long_price = round(trigger_price * (1 + long_grid_percentage), 2)
    else:  # short
        buy_price = round(trigger_price * (1 - short_grid_percentage), 2)
        close_long_price = round(trigger_price * (1 + short_grid_percentage), 2)
    return buy_price, close_long_price


def generate_signature(timestamp, method, request_path, body=""):
    """生成签名"""
    message = timestamp + method + request_path + body
    mac = hmac.new(SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def query_orders():
    """查询现有委托单"""
    endpoint = "/api/v5/trade/orders-pending"
    url = BASE_URL + endpoint

    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:23] + 'Z'
    sign = generate_signature(timestamp, "GET", endpoint)

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers)
        response_data = response.json()
        print(response_data)
        if response_data.get("code") == "0":
            orders = response_data.get("data", [])
            if orders:
                print("\n📋 当前委托单:")
                for order in orders:
                    side = order.get("side", "")
                    pos_side = order.get("posSide", "")
                    price = float(order.get("px", "0"))
                    size = float(order.get("sz", "0")) / 100
                    ord_id = order.get("ordId", "")
                    state = order.get("state", "")
                    print(
                        f"  {side.upper()} {pos_side.upper()}: 价格 {price:.2f} / 数量 {size:.4f} / 状态 {state} / ID {ord_id}")
            return orders
        else:
            print(f"❌ 查询订单失败: {response_data.get('msg')}")
            return []

    except Exception as e:
        print(f"❌ 查询订单发生错误: {str(e)}")
        return []


def cancel_order_rest_api(ord_id, inst_id):
    """使用 REST API 撤单"""
    endpoint = "/api/v5/trade/cancel-order"
    url = BASE_URL + endpoint
    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:23] + 'Z'

    cancel_data = {
        "ordId": ord_id,
        "instId": inst_id
    }
    cancel_json = json.dumps(cancel_data, separators=(',', ':'))

    sign = generate_signature(timestamp, "POST", endpoint, cancel_json)
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }

    response = requests.post(url, data=cancel_json, headers=headers)
    return response.json()


async def cancel_all_orders():
    """取消所有未完成的委托单"""
    orders = query_orders()
    for order in orders:
        ord_id = order.get('ordId')
        inst_id = order.get('instId')
        if ord_id and inst_id:
            cancel_response = cancel_order_rest_api(ord_id, inst_id)
            if cancel_response.get('code') == '0':
                print(f"✅ 撤单成功: {ord_id}")


def place_order(side, price, size, pos_side="long", is_close=False):
    """使用REST API下单"""
    endpoint = "/api/v5/trade/order"
    url = BASE_URL + endpoint
    timestamp = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:23] + 'Z'

    order_data = {
        "instId": "BTC-USDT-SWAP",
        "tdMode": "cross",
        "clOrdId": generate_clOrdId(side),
        "side": side,
        "ordType": "limit",
        "px": str(price),
        "sz": str(size * 100),
        "posSide": pos_side,
        "reduceOnly": "true" if is_close else "false"
    }

    order_json = json.dumps(order_data, separators=(',', ':'))
    sign = generate_signature(timestamp, "POST", endpoint, order_json)

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }

    response = requests.post(url, data=order_json, headers=headers)
    response_data = response.json()
    if response_data.get("code") == "0" and "data" in response_data and len(response_data["data"]) > 0:
        order_info = response_data["data"][0]
        order_id = order_info.get("ordId")
        if order_id:
            # 保存订单信息
            save_order_info(side, order_id, price, pos_side)
            return order_id
    print(f"❌ 下单失败：{response_data}")
    return None


async def order_listener(websocket):
    """监听订单更新"""
    global long_position, short_position, buy_ordId, close_long_ordId, long_trigger_price, short_trigger_price, long_take_profit_count, short_take_profit_count

    subscribe_msg = {"op": "subscribe", "args": [{"channel": "orders", "instType": "SWAP"}]}
    await websocket.send(json.dumps(subscribe_msg))
    print("📡 已订阅订单更新")

    while True:
        try:
            response = await websocket.recv()
            response_data = json.loads(response)

            if "data" in response_data and response_data.get("arg", {}).get("channel") == "orders":
                for order_info in response_data["data"]:
                    # 检查是否为BTC-USDT-SWAP的订单
                    if order_info.get("instId") != "BTC-USDT-SWAP":
                        continue

                    state = order_info.get("state")
                    side = order_info.get("side")
                    pos_side = order_info.get("posSide")
                    filled_size = float(order_info.get("accFillSz", "0")) / 100
                    order_price = float(order_info.get("px", "0"))
                    ordId = order_info.get("ordId")

                    # 验证订单是否由程序创建
                    order_type, _, _ = get_order_info(ordId)
                    if order_type is None:  # 如果订单不在记录中，说明不是程序创建的
                        continue

                    if state == "filled" and filled_size > 0:
                        buy_price, close_price = calculate_grid_prices(order_price, pos_side)

                        # 处理多单
                        if pos_side == "long" and enable_long_grid:
                            if side == "buy":
                                long_position += filled_size
                                if long_position < long_max_position:
                                    long_trigger_price = order_price
                                    print(f"\n✅ 开多成交")
                                    print(f"💰 当前多单持仓: {long_position}")
                                    print(f"🎯 多单触发价格: {long_trigger_price}")
                                    # 取消旧的平多单
                                    orders = query_orders()
                                    for order in orders:
                                        if order.get('side') == 'sell' and order.get('posSide') == 'long':
                                            # 验证订单是否由程序创建
                                            order_type, _, _ = get_order_info(order.get('ordId'))
                                            if order_type is not None:  # 只取消程序创建的订单
                                                cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                    # 重新委托买单和卖单
                                    place_order("buy", buy_price, long_grid_size, "long")
                                    place_order("sell", close_price, long_grid_size, "long", is_close=True)
                                    trigger_price = long_trigger_price
                                    grid_size = long_grid_size
                                    send_to_feishu(grid_size, grid_size, long_position, long_max_position,
                                                   trigger_price, 0,
                                                   buy_price, close_price, take_profit_count, 0, "多")
                                else:
                                    print('\n⚠️ 持仓已达到最大，停止买入')
                                    orders = query_orders()
                                    for order in orders:
                                        if order.get('side') == 'sell' and order.get('posSide') == 'long':
                                            # 验证订单是否由程序创建
                                            order_type, _, _ = get_order_info(order.get('ordId'))
                                            if order_type is not None:  # 只取消程序创建的订单
                                                cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                    place_order("sell", close_price, long_grid_size, "long", is_close=True)
                                    trigger_price = long_trigger_price
                                    grid_size = long_grid_size
                                    send_to_feishu(grid_size, grid_size, long_position, long_max_position,
                                                   trigger_price, 0,
                                                   buy_price, close_price, take_profit_count, 0, "多")
                            elif side == "sell":
                                long_position -= filled_size
                                long_trigger_price = order_price
                                long_take_profit_count += 1
                                print(f"\n✅ 平多成交")
                                print(f"💰 当前多单持仓: {long_position}")
                                print(f"🎯 多单触发价格: {long_trigger_price}")
                                orders = query_orders()
                                for order in orders:
                                    if order.get('side') == 'buy' and order.get('posSide') == 'long':
                                        # 验证订单是否由程序创建
                                        order_type, _, _ = get_order_info(order.get('ordId'))
                                        if order_type is not None:  # 只取消程序创建的订单
                                            cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                place_order("buy", buy_price, long_grid_size, "long")
                                place_order("sell", close_price, long_grid_size, "long", is_close=True)
                                trigger_price = long_trigger_price
                                grid_size = long_grid_size
                                send_to_feishu(grid_size, grid_size, long_position, long_max_position, trigger_price, 1,
                                               buy_price, close_price, take_profit_count, 0, "多")

                        # 处理空单
                        elif pos_side == "short" and enable_short_grid:
                            if side == "sell":
                                short_position += filled_size
                                if short_position < short_max_position:
                                    short_trigger_price = order_price
                                    print(f"\n✅ 开空成交")
                                    print(f"💰 当前空单持仓: {short_position}")
                                    print(f"🎯 空单触发价格: {short_trigger_price}")
                                    orders = query_orders()
                                    for order in orders:
                                        if order.get('side') == 'buy' and order.get('posSide') == 'short':
                                            cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                    place_order("sell", close_price, short_grid_size, "short")
                                    place_order("buy", buy_price, short_grid_size, "short", is_close=True)
                                    trigger_price = short_trigger_price
                                    grid_size = short_grid_size
                                    send_to_feishu(grid_size, grid_size, short_position, short_max_position,
                                                   trigger_price, 0,
                                                   close_price, buy_price, short_take_profit_count, 0, "空")
                                else:
                                    print('\n⚠️ 空单持仓已达到最大，停止卖出')
                                    orders = query_orders()
                                    for order in orders:
                                        if order.get('side') == 'buy' and order.get('posSide') == 'short':
                                            # 验证订单是否由程序创建
                                            order_type, _, _ = get_order_info(order.get('ordId'))
                                            if order_type is not None:  # 只取消程序创建的订单
                                                cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                    place_order("buy", buy_price, short_grid_size, "short", is_close=True)
                                    trigger_price = short_trigger_price
                                    grid_size = short_grid_size
                                    send_to_feishu(grid_size, grid_size, short_position, short_max_position,
                                                   trigger_price, 0,
                                                   close_price, buy_price, short_take_profit_count, 0, "空")
                            elif side == "buy":
                                short_position -= filled_size
                                short_trigger_price = order_price
                                short_take_profit_count += 1
                                print(f"\n✅ 平空成交")
                                print(f"💰 当前空单持仓: {short_position}")
                                print(f"🎯 空单触发价格: {short_trigger_price}")
                                orders = query_orders()
                                for order in orders:
                                    if order.get('side') == 'sell' and order.get('posSide') == 'short':
                                        # 验证订单是否由程序创建
                                        order_type, _, _ = get_order_info(order.get('ordId'))
                                        if order_type is not None:  # 只取消程序创建的订单
                                            cancel_order_rest_api(order.get('ordId'), order.get('instId'))
                                place_order("sell", close_price, short_grid_size, "short")
                                place_order("buy", buy_price, short_grid_size, "short", is_close=True)
                                trigger_price = short_trigger_price
                                grid_size = short_grid_size
                                send_to_feishu(grid_size, grid_size, short_position, short_max_position, trigger_price,
                                               1,
                                               close_price, buy_price, short_take_profit_count, 0, "空")

            await asyncio.sleep(0)

        except websockets.exceptions.ConnectionClosed:
            print("\n❌ WebSocket 连接断开，尝试重新连接...")
            await asyncio.sleep(5)
            return
        except Exception as e:
            print(f"\n⚠️ 监听异常: {e}")


def get_account_balance():
    """获取账户余额信息"""
    endpoint = "/api/v5/account/balance"
    url = BASE_URL + endpoint

    timestamp = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:23] + 'Z'
    sign = generate_signature(timestamp, "GET", endpoint)

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers)
        response_data = response.json()

        if response_data.get("code") == "0":
            data = response_data.get("data", [])
            if data:
                return float(data[0].get("totalEq", "0"))
        return 0

    except Exception as e:
        print(f"❌ 获取账户信息发生错误: {str(e)}")
        return 0


def send_to_feishu(grid_size, take_profit_size, current_position, max_position, trigger_price, action_type, buy_price,
                   close_long_price, take_profit_count, balance, pos_type):
    """发送消息到飞书"""
    url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_token}"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    headers = {
        "Content-Type": "application/json"
    }

    # 获取账户总价值和对应方向的止盈次数
    total_balance = get_account_balance()
    display_take_profit_count = long_take_profit_count if pos_type == "多" else short_take_profit_count

    # Determine action and template color based on action_type
    if action_type == 1:
        action = "止盈"  # Take profit
        template_color = "green"
    elif action_type == 0:
        action = "加仓"  # Increase position
        template_color = "orange"
    else:
        action = "未知"  # Unknown action
        template_color = "wathet"  # Default color

    data = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🤖【OKX-撸短机器人】🤖--{action}"
                },
                "template": template_color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**·交易对:** <font color='orange'>**BTC-U本位-{pos_type}平**</font>  \n"
                            f"**·触发价格:** <font color='blue'>**{trigger_price}**</font> **行为:** <font color='green'>**{action}**</font>  \n"
                            f"**·挂买单价格:** <font color='green'>**{buy_price}**</font> **数量:** <font color='green'>**{grid_size}**</font>  \n"
                            f"**·挂卖单价格:** <font color='red'>**{close_long_price}**</font> **数量:** <font color='red'>**{take_profit_size}**</font>  \n"
                            f"**·当前持仓量:** <font color='orange'>**{current_position:.3f}**</font>  \n"
                            f"**·最大持仓量:** <font color='orange'>**{max_position}**</font>  \n"
                            f"**·{pos_type}单止盈次数:** <font color='orange'>**{display_take_profit_count}**</font> **账户总价值:** <font color='orange'>**{total_balance:.2f} USDT**</font>  \n"
                            f"**·时间:** <font color='green'>**{current_time}**</font>"
                        )
                    }
                }
            ]
        }
    }

    response = requests.post(url, json=data, headers=headers)
    print(response.json())


async def connect_websocket():
    """WebSocket 连接管理"""
    global buy_ordId, close_long_ordId
    is_order_placed = False
    while True:
        try:
            async with websockets.connect("wss://ws.okx.com:8443/ws/v5/private") as websocket:
                # 认证
                timestamp = str(int(time.time()))
                message = timestamp + 'GET' + '/users/self/verify'
                signature = base64.b64encode(hmac.new(
                    SECRET_KEY.encode(), message.encode(), hashlib.sha256
                ).digest()).decode()

                auth_data = {
                    "op": "login",
                    "args": [
                        {
                            "apiKey": API_KEY,
                            "passphrase": PASSPHRASE,
                            "timestamp": timestamp,
                            "sign": signature
                        }
                    ]
                }
                await websocket.send(json.dumps(auth_data))
                response = await websocket.recv()
                print("✅ 认证结果:", response)

                if not is_order_placed:
                    # 根据配置决定是否委托多单
                    if enable_long_grid:
                        buy_price, close_long_price = calculate_grid_prices(long_trigger_price, "long")
                        buy_ordId = place_order("buy", buy_price, long_grid_size, "long")
                        close_long_ordId = place_order("sell", close_long_price, long_grid_size, "long", is_close=True)

                    # 根据配置决定是否委托空单
                    if enable_short_grid:
                        short_buy_price, short_close_price = calculate_grid_prices(short_trigger_price, "short")
                        place_order("sell", short_close_price, short_grid_size, "short")
                        place_order("buy", short_buy_price, short_grid_size, "short", is_close=True)

                    is_order_placed = True

                await order_listener(websocket)
        except Exception as e:
            print(f"⚠️ 连接错误: {e}，5秒后重试...")
            await asyncio.sleep(5)
            is_order_placed = False


if __name__ == "__main__":
    print("\n🚀 启动OKX网格交易机器人...\n")
    if enable_long_grid:
        print("📈 多单交易配置:")
        print(f"  • 当前持仓: {long_position}")
        print(f"  • 触发价格: {long_trigger_price}")
        print(f"  • 网格间距: {long_grid_percentage * 100}%")
        print(f"  • 交易数量: {long_grid_size}")
        print(f"  • 最大持仓: {long_max_position}\n")

    if enable_short_grid:
        print("📉 空单交易配置:")
        print(f"  • 当前持仓: {short_position}")
        print(f"  • 触发价格: {short_trigger_price}")
        print(f"  • 网格间距: {short_grid_percentage * 100}%")
        print(f"  • 交易数量: {short_grid_size}")
        print(f"  • 最大持仓: {short_max_position}\n")
    asyncio.run(connect_websocket())
