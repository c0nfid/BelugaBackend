from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app import database, models

router = APIRouter(
    prefix="/wiki",
    tags=["Wiki"]
)

@router.get("/enchantments")
def get_all_enchantments(db: Session = Depends(database.get_db)):
    results = db.query(
        models.Enchantment.name,
        models.Enchantment.display,
        models.Enchantment.ench_group,
        models.Enchantment.description,
        func.group_concat(models.EnchantmentItem.item).label("items") # Собираем .item
    ).outerjoin(
        models.EnchantmentItem, 
        models.Enchantment.name == models.EnchantmentItem.ench_name # Связь по имени
    ).group_by(
        models.Enchantment.name
    ).all()

    formatted_data = []
    for row in results:
        items_list = row.items.split(",") if row.items else []
        formatted_data.append({
            "id": row.name,
            "name": row.display or row.name,
            "rarity": row.ench_group or "default",
            "description": row.description,
            "items": items_list
        })
        
    return formatted_data

@router.get("/enchantments/{name}")
def get_enchantment_by_name(name: str, db: Session = Depends(database.get_db)):
    result = db.query(
        models.Enchantment.name,
        models.Enchantment.display,
        models.Enchantment.ench_group,
        models.Enchantment.description,
        models.Enchantment.max_level,
        func.group_concat(models.EnchantmentItem.item).label("items")
    ).outerjoin(
        models.EnchantmentItem, 
        models.Enchantment.name == models.EnchantmentItem.ench_name
    ).filter(
        models.Enchantment.name == name
    ).group_by(
        models.Enchantment.name
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Зачарование не найдено")

    return {
        "id": result.name,
        "name": result.display or result.name,
        "rarity": result.ench_group or "default",
        "description": result.description,
        "max_level": result.max_level,
        "items": result.items.split(",") if result.items else []
    }