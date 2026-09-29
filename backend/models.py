# models.py - обновленная версия с полем production_stage
from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

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