"""Routes for the auction integration API."""
from django.urls import path

from . import api

app_name = 'auction'

urlpatterns = [
    path('api/rubric/', api.auction_rubric, name='rubric'),
    path('api/cards/available/', api.available_cards, name='available-cards'),
    path('api/lots/create/', api.lot_create, name='lot-create'),
    path('api/lots/create-from-card/', api.lot_create_from_card, name='lot-create-from-card'),
    path('api/lots/<int:lot_id>/relist/', api.lot_relist, name='lot-relist'),
    path('api/lots/<int:lot_id>/bid/', api.lot_bid, name='lot-bid'),
    path('api/lots/<int:lot_id>/buy-now/', api.lot_buy_now, name='lot-buy-now'),
    path('api/lots/<int:lot_id>/edit/', api.lot_edit, name='lot-edit'),
    path('api/cards/<int:file_id>/status/', api.card_auction_status, name='card-status'),
]
