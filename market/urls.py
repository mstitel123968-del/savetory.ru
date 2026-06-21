"""Defines the Django routes that replace the Java market controllers."""
from django.urls import path

from . import api, views

urlpatterns = [
    path('', views.market_root, name='market_root'),
    path('shop/', views.market_shop, name='market_shop'),
    path('free/', views.market_free, name='market_free'),
    path('wanted/', views.market_wanted, name='market_wanted'),
    path('swap/', views.market_swap, name='market_swap'),
    path('auction/', views.market_auction, name='market_auction'),
    path('auction/create/', views.market_auction_create, name='market_auction_create'),
    path('auction/<int:listing_id>/', views.market_auction_detail, name='market_auction_detail'),
    path('auction/<slug:category_slug>/', views.market_auction, name='market_auction_by_cat'),
    path('listing/<int:pk>/', views.market_listing_detail, name='market_listing_detail'),
    path('api/create/', api.listing_create, name='market_api_create'),
    path('api/bid/', api.auction_bid, name='market_api_bid'),
    path('api/auction/card/<int:file_id>/status/', api.auction_card_status, name='market_api_auction_card_status'),
    path('api/auction/card-status/', api.auction_card_status_by_card, name='market_api_auction_card_status_by_card'),
    path('api/auction/draft/', api.auction_draft_create, name='market_api_auction_draft_create'),
    path('api/auction/draft/<int:listing_id>/', api.auction_draft_manage, name='market_api_auction_draft_manage'),
    path('api/auction/draft/<int:listing_id>/publish/', api.auction_draft_publish, name='market_api_auction_draft_publish'),
    path('api/auction/<int:listing_id>/state/', api.auction_state, name='market_api_auction_state'),
    path('api/auction/<int:listing_id>/bid/', api.auction_bid_place, name='market_api_auction_bid'),
    path('api/auction/<int:listing_id>/bids/', api.auction_bids, name='market_api_auction_bids'),
    path('api/auction/<int:listing_id>/manage/', api.auction_manage, name='market_api_auction_manage'),
    path('api/auction/<int:listing_id>/cancel/', api.auction_cancel, name='market_api_auction_cancel'),
    path('api/auction/<int:listing_id>/relist/', api.auction_relist, name='market_api_auction_relist'),
]
