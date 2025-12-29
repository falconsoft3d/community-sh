from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

class BlogPost(models.Model):
    """Blog post model with Markdown support"""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    content = models.TextField(help_text="Write your content in Markdown")
    excerpt = models.TextField(max_length=300, blank=True, help_text="Short description")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blog_posts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published = models.BooleanField(default=False)
    featured = models.BooleanField(default=False, help_text="Show on homepage")
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)
    
    @property
    def reading_time(self):
        """Estimate reading time in minutes"""
        words = len(self.content.split())
        return max(1, words // 200)  # Average reading speed
