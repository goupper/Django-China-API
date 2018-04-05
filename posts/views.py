import datetime
from collections import OrderedDict

from django.utils.timezone import now
from django.db.models import Max, Count
from django_filters import rest_framework as filters
from rest_framework import permissions, viewsets, pagination, serializers, status
from rest_framework.decorators import list_route
from rest_framework.response import Response

from .models import Post
from tags.models import Tag
from .serializers import (
    IndexPostListSerializer,
    PopularPostSerializer,
    PostDetailSerializer,
)
from .permissions import IsAdminAuthorOrReadOnly


class PostPagination(pagination.PageNumberPagination):
    page_size = 20

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('posts', data)
        ]))


class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.annotate(
        latest_reply_time=Max('replies__submit_date')
    ).order_by('-pinned', '-latest_reply_time', '-created_time')
    serializer_class = IndexPostListSerializer
    permission_classes = (permissions.IsAuthenticatedOrReadOnly,
                          IsAdminAuthorOrReadOnly)
    pagination_class = PostPagination
    # 允许get post put方法
    http_method_names = ['get', 'post', 'put', 'patch']
    filter_backends = (filters.DjangoFilterBackend,)
    # 在post-list页面可以按标签字段过滤出特定标签下的帖子
    filter_fields = ('tags',)

    def retrieve(self, request, *args, **kwargs):
        """
        重写帖子详情页，这里使用PostDetailSerializer，
        而不是默认的IndexPostListSerializer
        """
        instance = self.get_object()
        serializer = PostDetailSerializer(instance, context={'request': request})
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        重写创建帖子方法，使用PostDetailSerializer
        """
        serializer = PostDetailSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """
        保存tags和author，同时验证tag的数量
        tags和author在PostSerializer里是read_only
        """
        tags_data = self.request.data.get('tags')
        tags = []
        if not tags_data:
            raise serializers.ValidationError(detail={'标签': '请选择至少一个标签'})
        elif len(tags_data) > 3:
            raise serializers.ValidationError(detail={'标签': '最多可以选择三个标签'})
        for name in tags_data:
            try:
                tag = Tag.objects.get(name=name)
                tags.append(tag)
            except Exception:
                raise serializers.ValidationError(detail={'标签': '标签不存在'})
        serializer.save(author=self.request.user, tags=tags)

    def update(self, request, *args, **kwargs):
        """
        更新帖子的方法，包括put和patch，
        """
        partial = kwargs.pop('partial', False)
        tags_data = request.data.get('tags')
        if partial and tags_data is None:
            pass
        elif not tags_data:
            raise serializers.ValidationError(detail={'标签': '请选择至少一个标签'})
        elif len(tags_data) > 3:
            raise serializers.ValidationError(detail={'标签': '最多可以选择三个标签'})
        instance = self.get_object()
        serializer = PostDetailSerializer(
            instance,
            data=request.data,
            partial=partial,
            context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def perform_update(self, serializer):
        tags_data = self.request.data.get('tags')
        tags = []
        if tags_data:
            for name in tags_data:
                try:
                    tag = Tag.objects.get(name=name)
                    tags.append(tag)
                except Exception:
                    raise serializers.ValidationError(detail={'标签': '标签不存在'})
            serializer.save(tags=tags)
        else:
            serializer.save()

    @list_route(serializer_class=PopularPostSerializer)
    def popular(self, request):
        """
        返回48小时内评论次数最多的帖子
        """
        popular_posts = Post.public.annotate(
            num_replies=Count('replies'),
            latest_reply_time=Max('replies__submit_date')
        ).filter(
            num_replies__gt=0,
            latest_reply_time__gt=(now() - datetime.timedelta(days=2)),
            latest_reply_time__lt=now()
        ).order_by('-num_replies', '-latest_reply_time')[:10]
        serializer = self.get_serializer(popular_posts, many=True)
        return Response(serializer.data)
