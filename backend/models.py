# models.py - обновленная версия с полем production_stage
from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class ScheduleCell(Base):
    """Ячейка листа графика, хранимая в базе.

    Нужна, чтобы правка графика (добавление сотрудника в участок, очистка,
    редактирование любой ячейки) работала без перезаписи xlsx-файла:
    файл остаётся источником для импорта и для выгрузки.
    """
    __tablename__ = 'schedule_cells'
    id = Column(Integer, primary_key=True)
    year = Column(Integer, index=True)
    month = Column(Integer, index=True)
    row = Column(Integer, index=True)
    col = Column(Integer, index=True)
    value = Column(String, default='')


class ScheduleMerge(Base):
    """Объединённая ячейка листа графика (участки, заголовки, шапка).

    Хранится вместе с ячейками: при добавлении строк объединения нужно
    сдвигать так же, как значения, иначе участки «съезжают».
    """
    __tablename__ = 'schedule_merges'
    id = Column(Integer, primary_key=True)
    year = Column(Integer, index=True)
    month = Column(Integer, index=True)
    row1 = Column(Integer)
    col1 = Column(Integer)
    row2 = Column(Integer)
    col2 = Column(Integer)

class Employee(Base):
    __tablename__ = 'employees'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    position = Column(String)
    department = Column(String)
    order = Column(Integer, default=0)  # Порядок из файла
    tab_number = Column(String, nullable=True)  # Табельный номер

class Plan(Base):
    __tablename__ = 'plans'
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey('employees.id'))
    date = Column(Date)
    plan_type = Column(String)

class Fact(Base):
    __tablename__ = 'facts'
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey('employees.id'))
    date = Column(Date)
    start_time = Column(String, nullable=True)   # Приход (например, "08:00")
    end_time = Column(String, nullable=True)     # Уход (например, "17:00")
    fact_hours = Column(Float, default=0.0)      # Фактические часы (расчетные)
    production_stage = Column(String, nullable=True)  # НОВОЕ ПОЛЕ: Этапы производства


class MealOverride(Base):
    """Правило питания для сотрудника (кнопки «Добавить», «Исключить», «Замена»).

    mode:
      include — всегда попадает в список, даже если в графике отпуск/больничный;
      exclude — не попадает в список, даже если в графике есть работа;
      replace — вместо него в список пишется другой сотрудник (replacement).
    """
    __tablename__ = 'meal_overrides'
    id = Column(Integer, primary_key=True)
    employee_name = Column(String, unique=True, nullable=False)
    mode = Column(String, nullable=False)
    replacement = Column(String, nullable=True)