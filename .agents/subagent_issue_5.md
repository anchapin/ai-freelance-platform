# Subagent Task: Issue #5

## Issue: Refactor overloaded Task model using composition pattern

**Repository**: /home/alexc/Projects/ArbitrageAI  
**Worktree**: main-issue-5  
**Branch**: feature/task-composition  
**Priority**: P1

## Problem Statement
The Task SQLAlchemy model has 30+ columns covering multiple concerns (execution, planning, review, arena, file storage), violating separation of concerns. Single rows are 50+ KB with execution logs. Adding new features requires full schema migrations.

## Objective
Decompose Task into focused entities using composition pattern for better maintainability and testability.

## New Entity Structure

### 1. Task (Core)
Reduced to core fields only (~10 fields):
```python
class Task(Base):
    __tablename__ = "tasks"
    
    id: str = Column(String, primary_key=True)
    title: str = Column(String, nullable=False)
    description: str = Column(String)
    domain: str = Column(String)
    status: TaskStatus = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    stripe_session_id: str = Column(String, unique=True)
    client_email: str = Column(String)
    amount_paid: float = Column(Float)
    delivery_token: str = Column(String)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    execution = relationship("TaskExecution", uselist=False, cascade="all, delete-orphan")
    planning = relationship("TaskPlanning", uselist=False, cascade="all, delete-orphan")
    review = relationship("TaskReview", uselist=False, cascade="all, delete-orphan")
    arena = relationship("TaskArena", uselist=False, cascade="all, delete-orphan")
    outputs = relationship("TaskOutput", cascade="all, delete-orphan")
```

### 2. TaskExecution (Execution-specific)
```python
class TaskExecution(Base):
    __tablename__ = "task_executions"
    
    id: str = Column(String, primary_key=True)
    task_id: str = Column(String, ForeignKey("tasks.id"), unique=True)
    status: ExecutionStatus = Column(Enum(ExecutionStatus))
    retry_count: int = Column(Integer, default=0)
    error_message: Optional[str] = Column(String)
    execution_logs: Dict = Column(JSON)  # Move from Task
    sandbox_result: Optional[Dict] = Column(JSON)
    artifacts: Optional[Dict] = Column(JSON)
    started_at: Optional[datetime] = Column(DateTime)
    completed_at: Optional[datetime] = Column(DateTime)
```

### 3. TaskPlanning (Planning-specific)
```python
class TaskPlanning(Base):
    __tablename__ = "task_planning"
    
    id: str = Column(String, primary_key=True)
    task_id: str = Column(String, ForeignKey("tasks.id"), unique=True)
    status: PlanningStatus = Column(Enum(PlanningStatus))
    plan_content: Optional[str] = Column(String)
    research_findings: Optional[Dict] = Column(JSON)
    file_type: Optional[str] = Column(String)  # From old model
    file_content: Optional[bytes] = Column(LargeBinary)
    filename: Optional[str] = Column(String)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
```

### 4. TaskReview (Review-specific)
```python
class TaskReview(Base):
    __tablename__ = "task_reviews"
    
    id: str = Column(String, primary_key=True)
    task_id: str = Column(String, ForeignKey("tasks.id"), unique=True)
    status: ReviewStatus = Column(Enum(ReviewStatus))
    review_feedback: Optional[str] = Column(String)
    reviewer_id: Optional[str] = Column(String)
    needs_escalation: bool = Column(Boolean, default=False)
    escalation_reason: Optional[str] = Column(String)
    reviewed_at: Optional[datetime] = Column(DateTime)
```

### 5. TaskArena (Arena-specific)
```python
class TaskArena(Base):
    __tablename__ = "task_arenas"
    
    id: str = Column(String, primary_key=True)
    task_id: str = Column(String, ForeignKey("tasks.id"), unique=True)
    competition_id: Optional[str] = Column(String)
    winning_model: Optional[str] = Column(String)
    local_score: Optional[float] = Column(Float)
    cloud_score: Optional[float] = Column(Float)
    profit_score: Optional[float] = Column(Float)
    local_result: Optional[Dict] = Column(JSON)
    cloud_result: Optional[Dict] = Column(JSON)
```

### 6. TaskOutput (Polymorphic results)
```python
class TaskOutput(Base):
    __tablename__ = "task_outputs"
    
    id: str = Column(String, primary_key=True)
    task_id: str = Column(String, ForeignKey("tasks.id"))
    output_type: OutputType = Column(Enum(OutputType))  # IMAGE, DOCUMENT, SPREADSHEET, etc
    output_url: Optional[str] = Column(String)
    output_data: Optional[Dict] = Column(JSON)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    
    # Unique constraint: one output per type per task
    __table_args__ = (UniqueConstraint('task_id', 'output_type', name='unique_task_output_type'),)
```

## Implementation Steps

### 1. Create New Model Classes (src/api/models.py)
- Define all 6 entities with proper relationships
- Add validation methods to each entity
- Use cascade delete to maintain referential integrity
- Add helper properties for backward compatibility

### 2. Add State Machine Validation
Create state machine rules:
```python
class TaskStateValidator:
    VALID_TRANSITIONS = {
        TaskStatus.PENDING: [TaskStatus.EXECUTING],
        TaskStatus.EXECUTING: [TaskStatus.REVIEWING, TaskStatus.FAILED],
        TaskStatus.REVIEWING: [TaskStatus.COMPLETED, TaskStatus.NEEDS_REVISION],
        TaskStatus.NEEDS_REVISION: [TaskStatus.EXECUTING],
        TaskStatus.FAILED: [TaskStatus.PENDING],
    }
    
    def validate_transition(self, from_status, to_status) -> bool:
        return to_status in self.VALID_TRANSITIONS.get(from_status, [])
```

Add validation hooks to Task:
```python
@validates('status')
def validate_status(self, key, new_status):
    if not TaskStateValidator.validate_transition(self.status, new_status):
        raise ValueError(f"Invalid transition: {self.status} → {new_status}")
    return new_status
```

### 3. Create Database Migration (alembic)
Generate migration script:
```bash
alembic revision --autogenerate -m "Refactor Task model to composition pattern"
```

Manual migration steps:
1. Create new tables (TaskExecution, TaskPlanning, TaskReview, TaskArena, TaskOutput)
2. Migrate data from Task to new tables
3. Add indexes for performance
4. Drop old columns from Task
5. Test rollback capability

### 4. Update API Endpoints (src/api/main.py)
Update all endpoints that create/read/update Task:
- Add helper methods to Task for accessing related entities:
  ```python
  class Task:
      @property
      def execution_status(self):
          return self.execution.status if self.execution else None
      
      def get_outputs_by_type(self, output_type):
          return [o for o in self.outputs if o.output_type == output_type]
  ```
- Update response schemas to flatten related entities
- Ensure backward compatibility with existing API clients

### 5. Write Tests
**Unit Tests**:
- Test each entity model individually
- Test relationships and cascade deletes
- Test validation methods

**State Machine Tests**:
- Test valid transitions
- Test invalid transitions raise errors
- Test state machine from end-to-end

**Migration Tests**:
- Test migration creates new tables
- Test data migrated correctly
- Test rollback works
- Test no data loss

**Integration Tests**:
- Test API endpoints with new models
- Test task creation/update/delete
- Test queries across related entities
- Test backward compatibility

## Files to Modify
- `src/api/models.py` - Define new entities, reduce Task
- `src/api/main.py` - Update all endpoint handlers
- `src/api/database.py` - Update session management if needed
- `src/api/schemas.py` - Update request/response schemas
- `alembic/versions/` - Add migration script
- `tests/test_models.py` - Comprehensive model tests
- `tests/test_state_machine.py` - State validation tests
- `tests/test_migrations.py` - Migration tests

## Testing Requirements
- ✓ Task model reduced to <15 fields
- ✓ New entities created with proper relationships
- ✓ State machine validation working
- ✓ Migration script created
- ✓ Migration tested (including rollback)
- ✓ All API endpoints working with new models
- ✓ Backward compatibility maintained
- ✓ 100% test coverage for new models
- ✓ No data loss during migration
- ✓ Performance: queries not slower than before

## Acceptance Criteria
- [ ] Task model reduced to <15 fields
- [ ] New composition entities created with ForeignKeys
- [ ] All relationships properly defined
- [ ] State machine validation preventing invalid transitions
- [ ] Migration script provided and tested
- [ ] All API endpoints updated
- [ ] Backward compatibility verified
- [ ] 100% test coverage for new models

## Timeline
Estimated: 8-10 hours

## Notes
- Coordinate with Issue #6 (Vector DB decouple) - may affect executor
- Test migration on production-like data volume
- Consider adding feature flag for gradual rollout
- Plan database downtime for migration if needed
