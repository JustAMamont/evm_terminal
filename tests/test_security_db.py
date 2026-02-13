import pytest
from bot.core.db_manager import DatabaseManager

@pytest.mark.asyncio
async def test_db_encryption_flow():
    # Создаем чистый экземпляр для проверки процесса шифрования с нуля.
    db = DatabaseManager(":memory:", ":memory:")
    await db.connect()
    
    try:
        # 1. Проверяем, что БД изначально не зашифрована
        assert await db.is_encrypted() is False
        
        # 2. Устанавливаем мастер-пароль
        password = "super_secret_365"
        await db.set_password(password)
        
        # Теперь должна быть зашифрована
        assert await db.is_encrypted() is True
        
        # 3. Добавляем кошелек (он должен зашифроваться внутри add_wallet)
        pk = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        addr = "0xWalletAddress"
        await db.add_wallet(addr, pk, "Main Wallet", True)
        
        # 4. Проверяем "сырые" данные в БД - ключ должен быть зашифрован (не равен исходному)
        wallets_raw = await db.get_all_wallets_raw()
        encrypted_pk = wallets_raw[0]['private_key']
        assert encrypted_pk != pk
        assert len(encrypted_pk) > len(pk)
        
        # 5. Проверяем расшифровку через get_wallet_with_pk
        wallet_decrypted = await db.get_wallet_with_pk(addr)
        assert wallet_decrypted['private_key'] == pk
        
    finally:
        await db.close()

@pytest.mark.asyncio
async def test_db_unlock_fail(db_manager: DatabaseManager):
    # Здесь используем фикстуру db_manager, у которой пароль "test_password_123" (из conftest)
    
    # Пытаемся разблокировать неверным паролем
    success = await db_manager.unlock_db("wrong_pass")
    assert success is False
    
    # Верным паролем (который задан в conftest.py)
    success = await db_manager.unlock_db("test_password_123")
    assert success is True