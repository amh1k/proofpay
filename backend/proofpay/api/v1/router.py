"""Versioned API router for the frontend contract."""

from fastapi import APIRouter

from . import auth, dashboard, demo, orders, reviews, transactions, verifications

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(orders.router)
router.include_router(transactions.router)
router.include_router(verifications.router)
router.include_router(verifications.claims_router)
router.include_router(reviews.router)
router.include_router(reviews.verification_router)
router.include_router(demo.router)
