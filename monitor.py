import ccxt
import os
import json
import logging
import asyncio
import telegram
from dotenv import load_dotenv
from datetime import datetime

# --- 로깅 설정 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 상수 정의 ---
SNAPSHOT_FILE = 'snapshot_coins.json' # 5% 이상 상승 포착 종목 저장 파일
REPORT_INTERVAL_MINUTES = 60 # 리포트 주기 (분)

def load_snapshot():
    """스냅샷 파일을 불러옵니다. 파일이 없으면 빈 집합(set)을 반환합니다."""
    if not os.path.exists(SNAPSHOT_FILE):
        return set()
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            # JSON 파일에서 리스트를 불러와 set으로 변환
            return set(json.load(f))
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"스냅샷 파일 로딩 실패: {e}")
        return set()

def save_snapshot(symbols):
    """종목 심볼 집합(set)을 스냅샷 파일에 저장합니다."""
    try:
        with open(SNAPSHOT_FILE, 'w') as f:
            # set을 list로 변환하여 JSON으로 저장
            json.dump(list(symbols), f, indent=4)
    except IOError as e:
        logging.error(f"스냅샷 파일 저장 실패: {e}")

async def send_telegram_message(bot, chat_id, message):
    """텔레그램 메시지를 비동기로 전송하는 함수"""
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        logging.info("텔레그램 메시지 전송 성공.")
    except Exception as e:
        logging.error(f"텔레그램 메시지 전송 실패: {e}")

async def main():
    """메인 실행 함수"""
    # --- 환경 변수 로드 ---
    load_dotenv()
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        logging.error("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 .env 또는 Github Secrets에 설정되지 않았습니다.")
        return

    bot = telegram.Bot(token=bot_token)
    upbit = ccxt.upbit()

    # --- 스냅샷 및 신규 포착 종목 로직 ---
    try:
        upbit.load_markets()
        krw_symbols = [symbol for symbol in upbit.symbols if symbol.endswith('/KRW')]
        tickers = upbit.fetch_tickers(symbols=krw_symbols)

        previous_snapshot = load_snapshot()
        current_snapshot = set(previous_snapshot) # 이전 기록을 복사하여 시작
        newly_detected = set()

        logging.info("업비트 KRW 마켓 5% 이상 상승 종목 스캔 시작...")

        for symbol, ticker in tickers.items():
            # 'percentage' 필드가 있고, None이 아니며 5% 이상인 경우
            if ticker.get('percentage') is not None and ticker['percentage'] >= 5:
                # 이전에 포착되지 않았던 새로운 종목인 경우
                if symbol not in previous_snapshot:
                    logging.info(f"🚀 신규 5% 이상 상승 포착: {symbol} ({ticker['percentage']:.2f}%)")
                    current_snapshot.add(symbol)
                    newly_detected.add(symbol)

        if newly_detected:
            logging.info(f"총 {len(newly_detected)}개의 신규 종목 포착. 스냅샷 업데이트...")
            save_snapshot(current_snapshot)
        else:
            logging.info("새롭게 5% 이상 상승한 종목 없음.")

    except Exception as e:
        logging.error(f"종목 스캔 중 오류 발생: {e}")
        await send_telegram_message(bot, chat_id, f"오류 발생: {e}")

    # --- 리포트 전송 로직 (매시 정각에 가까운 시간에 실행될 때) ---
    now = datetime.now()
    # GitHub Actions cron 주기가 15분이므로, 0~14분 사이에 실행될 때를 리포트 시간으로 간주
    if now.minute < 15:
        snapshot_to_report = load_snapshot()
        if snapshot_to_report:
            logging.info(f"리포트 시간({now.hour}시). 저장된 {len(snapshot_to_report)}개 종목에 대한 리포트를 전송합니다.")
            
            message = f"- 지난 1시간 동안 5% 이상 상승을 기록한 종목 목록 -\n"
            message += "\n".join(sorted(list(snapshot_to_report)))
            
            await send_telegram_message(bot, chat_id, message)
            
            # 리포트 후 스냅샷 파일 초기화
            logging.info("리포트 전송 완료. 다음 1시간을 위해 스냅샷을 초기화합니다.")
            save_snapshot(set())
        else:
            logging.info(f"리포트 시간({now.hour}시)이지만, 지난 1시간 동안 포착된 종목이 없어 리포트를 건너뜁니다.")


if __name__ == "__main__":
    asyncio.run(main())
