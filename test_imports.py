"""
Тест импортов и конфигурации
"""
import sys
print("Python version:", sys.version)
print("\n=== Проверка импортов ===\n")

try:
    import aiogram
    print("✓ aiogram импортирован успешно")
except Exception as e:
    print(f"✗ Ошибка импорта aiogram: {e}")

try:
    from config import settings
    print("✓ config импортирован успешно")
except Exception as e:
    print(f"✗ Ошибка импорта config: {e}")

try:
    from config import calculate_commission
    print("✓ calculate_commission импортирована успешно")
    
    # Тест расчета комиссии
    print("\n=== Тест расчета комиссии ===\n")
    
    test_cases = [
        (2000, "< 2500₽"),
        (2500, "= 2500₽"),
        (3000, "2500-4500₽"),
        (4500, "= 4500₽"),
        (5000, "> 4500₽"),
    ]
    
    for amount, desc in test_cases:
        commission = calculate_commission(amount)
        percent = (commission / amount) * 100
        print(f"Сумма: {amount:>5}₽ ({desc:>12}) → Комиссия: {commission:>6.2f}₽ ({percent:.1f}%)")
        
except Exception as e:
    print(f"✗ Ошибка: {e}")
    import traceback
    traceback.print_exc()

try:
    from database import models
    print("\n✓ database.models импортированы успешно")
except Exception as e:
    print(f"\n✗ Ошибка импорта database.models: {e}")

try:
    from services import UserService
    print("✓ services импортированы успешно")
except Exception as e:
    print(f"✗ Ошибка импорта services: {e}")

try:
    from bot import handlers
    print("✓ bot.handlers импортированы успешно")
except Exception as e:
    print(f"✗ Ошибка импорта bot.handlers: {e}")

print("\n=== Проверка завершена ===")
