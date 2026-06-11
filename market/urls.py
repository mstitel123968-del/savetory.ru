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
    path('auction/<slug:category_slug>/', views.market_auction, name='market_auction_by_cat'),
    path('listing/<int:pk>/', views.market_listing_detail, name='market_listing_detail'),
    path('api/create/', api.listing_create, name='market_api_create'),
    path('api/bid/', api.auction_bid, name='market_api_bid'),
]
