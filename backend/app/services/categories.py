"""Category management (§3.4, D-080).

Categories are labels kept outside the chart of accounts, so renaming or moving one never
touches a posting. Rules:
- a name is unique per user and kind, ignoring case;
- the kind is fixed once made (transactions on it were checked against it, I8);
- one level of nesting: a parent is a top-level category of the same kind, not archived, and a
  category with subcategories cannot itself become one;
- archiving only stops new use (I8); history keeps the label. Archiving a parent archives its
  subcategories, and a subcategory comes back only while its parent is active.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ledger import Category, CategoryKind
from app.services.ledger import NotFound, RuleViolation

_UNSET = object()  # "parent_id not given", as opposed to None ("move to the top")


def get(session: Session, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    """The user's category, locked for the change. Another user's is NotFound (§7)."""
    cat = session.scalars(
        select(Category)
        .where(Category.id == category_id, Category.user_id == user_id)
        .with_for_update()
    ).one_or_none()
    if cat is None:
        raise NotFound(f"category {category_id}")
    return cat


def _children(session: Session, user_id: uuid.UUID, cat: Category) -> list[Category]:
    q = select(Category).where(Category.user_id == user_id, Category.parent_id == cat.id)
    return list(session.scalars(q))


def _check_name(
    session: Session,
    user_id: uuid.UUID,
    name: str,
    kind: CategoryKind,
    skip: uuid.UUID | None = None,  # the category being renamed, which may keep its own name
) -> str:
    name = name.strip()
    if not name:
        raise RuleViolation("category", "give it a name")
    clash = session.scalars(
        select(Category.id).where(
            Category.user_id == user_id,
            Category.kind == kind,
            func.lower(Category.name) == name.lower(),
            Category.id.is_distinct_from(skip),  # true for every row when skip is None
        )
    ).first()
    if clash is not None:
        label = "a spending" if kind is CategoryKind.expense else "an income"
        raise RuleViolation("category", f"{name} already exists as {label} category")
    return name


def _check_parent(
    session: Session, user_id: uuid.UUID, parent_id: uuid.UUID, kind: CategoryKind
) -> Category:
    parent = get(session, user_id, parent_id)
    if parent.kind is not kind:
        other = "a spending" if parent.kind is CategoryKind.expense else "an income"
        raise RuleViolation("category", f"{parent.name} is {other} category")
    if parent.parent_id is not None:
        raise RuleViolation("category", f"{parent.name} is already a subcategory; one level only")
    if parent.is_archived:
        raise RuleViolation("category", f"{parent.name} is archived")
    return parent


def create(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    kind: CategoryKind,
    parent_id: uuid.UUID | None = None,
) -> Category:
    kind = CategoryKind(kind)
    name = _check_name(session, user_id, name, kind)
    if parent_id is not None:
        _check_parent(session, user_id, parent_id, kind)
    cat = Category(user_id=user_id, name=name, kind=kind, parent_id=parent_id)
    session.add(cat)
    session.flush()
    return cat


def edit(
    session: Session,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    *,
    name: str | None = None,
    parent_id: uuid.UUID | None | object = _UNSET,
    kind: CategoryKind | None = None,
) -> Category:
    """Rename, or move under a parent (`parent_id`) or back to the top (`parent_id=None`)."""
    cat = get(session, user_id, category_id)
    if kind is not None and CategoryKind(kind) is not cat.kind:
        raise RuleViolation("category", "a category's kind cannot change; make a new one")
    if name is not None:
        cat.name = _check_name(session, user_id, name, cat.kind, skip=cat.id)
    if parent_id is not _UNSET and parent_id is not None:
        assert isinstance(parent_id, uuid.UUID)
        if parent_id == cat.id:
            raise RuleViolation("category", "a category cannot be its own parent")
        if _children(session, user_id, cat):
            raise RuleViolation("category", f"{cat.name} has subcategories; one level only")
        _check_parent(session, user_id, parent_id, cat.kind)
    if parent_id is not _UNSET:
        cat.parent_id = parent_id  # type: ignore[assignment]  # checked above
    session.flush()
    return cat


def set_archived(
    session: Session, user_id: uuid.UUID, category_id: uuid.UUID, archived: bool
) -> Category:
    cat = get(session, user_id, category_id)
    if archived:
        for child in _children(session, user_id, cat):
            child.is_archived = True
    elif cat.parent_id is not None and get(session, user_id, cat.parent_id).is_archived:
        raise RuleViolation("category", "bring its parent back first")
    cat.is_archived = archived
    session.flush()
    return cat
