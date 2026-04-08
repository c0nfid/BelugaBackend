import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app import database, models, auth_utils

router = APIRouter(prefix="/api/shop", tags=["Shop"])

class BuyPayload(BaseModel):
    quantity: int = 1
    variant_index: Optional[int] = None

@router.get("/catalog")
def get_catalog(db: Session = Depends(database.get_db)):
    categories = db.query(models.ShopCategory).order_by(models.ShopCategory.sort_order).all()
    result =[]
    
    for cat in categories:
        products = db.query(models.ShopProduct).filter(
            models.ShopProduct.category_id == cat.id,
            models.ShopProduct.is_active == True
        ).all()
        
        prods_data =[]
        for p in products:
            # ОЧИЩАЕМ ВАРИАНТЫ: Отдаем фронтенду только name и price
            variants_data = None
            if p.variants:
                raw_variants = json.loads(p.variants)
                variants_data = [{"name": v["name"], "price": v["price"]} for v in raw_variants]

            prods_data.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "currency_type": p.currency_type,
                "image_url": p.image_url,
                "allow_quantity": p.allow_quantity,
                "variants": variants_data
            })
            
        if prods_data:
            result.append({
                "id": cat.id,
                "name": cat.name,
                "products": prods_data
            })
            
    return result

@router.post("/buy/{product_id}")
def buy_product(
    product_id: int, 
    payload: BuyPayload,
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    try:
        product = db.query(models.ShopProduct).filter(
            models.ShopProduct.id == product_id, 
            models.ShopProduct.is_active == True
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail="Товар не найден")

        player_data = db.query(models.PlayerData).filter(
            models.PlayerData.player_name == user.playername
        ).with_for_update().first()

        if not player_data:
            raise HTTPException(status_code=404, detail="Данные игрока не найдены")

        # Вычисляем итоговую цену и команду
        actual_price = product.price
        final_command = product.command_template
        
        if product.variants and payload.variant_index is not None:
            variants = json.loads(product.variants)
            if payload.variant_index < 0 or payload.variant_index >= len(variants):
                raise HTTPException(status_code=400, detail="Неверный тариф")
            
            selected = variants[payload.variant_index]
            actual_price = selected["price"]
            final_command = selected["command"]
            
        elif product.allow_quantity:
            if payload.quantity < 1 or payload.quantity > 64:
                raise HTTPException(status_code=400, detail="Неверное количество (от 1 до 64)")
            
            actual_price = product.price * payload.quantity
            final_command = final_command.replace("{amount}", str(payload.quantity))
        else:
            final_command = final_command.replace("{amount}", product.amount)

        order_id = str(uuid.uuid4())

        # ==========================================
        # ВЕТВЬ 1: ПОКУПКА ЗА РЕАЛЬНЫЕ ДЕНЬГИ (РУБЛИ)
        # ==========================================
        if product.currency_type == "rub":
            # Пишем лог со статусом pending (ожидает оплаты)
            purchase_log = models.ShopPurchaseLog(
                id=order_id, player_name=user.playername,
                product_id=product.id, price_paid=actual_price,
                currency_type="rub", status="pending"
            )
            db.add(purchase_log)
            db.commit()

            dummy_payment_url = f"https://example-payment-gateway.com/pay?order={order_id}&amount={actual_price}"

            return {
                "status": "payment_redirect", 
                "payment_url": dummy_payment_url,
                "message": "Перенаправление на страницу оплаты..."
            }

        else:
            if product.currency_type == "donate":
                if player_data.donation_balance < actual_price:
                    raise HTTPException(status_code=400, detail="Недостаточно Fish-баксов")
                player_data.donation_balance -= actual_price
                
            elif product.currency_type == "soft":
                if player_data.balance < actual_price:
                    raise HTTPException(status_code=400, detail="Недостаточно монет")
                player_data.balance -= actual_price

            final_command = final_command.replace("{item}", product.item_id)\
                .replace("{player}", user.playername)\
                .replace("{uuid}", user.uuid)\
                .replace("{external_order_id}", order_id)

            purchase_log = models.ShopPurchaseLog(
                id=order_id, player_name=user.playername,
                product_id=product.id, price_paid=actual_price,
                currency_type=product.currency_type,
                status="completed"
            )
            db.add(purchase_log)

            queue_entry = models.WebstoreQueue(
                external_order_id=order_id, player_uuid=user.uuid, player_name=user.playername,
                command_text=final_command, require_online=product.require_online,
                required_free_slots=product.required_free_slots,
                success_message=f"&aЗаказ {order_id} успешно выдан!",
                failure_message="&cОсвободите место в инвентаре для получения покупки!",
                status="PENDING"
            )
            db.add(queue_entry)

            db.commit()
            return {"status": "success", "message": "Покупка успешно отправлена на сервер!"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Buy Error: {e}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")