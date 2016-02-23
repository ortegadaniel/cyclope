from django.shortcuts import render, redirect
from django import forms
from cyclope.apps.medialibrary.models import Picture
from cyclope.apps.medialibrary.forms import InlinedPictureForm
from django.views.decorators.http import require_POST
from django.core.urlresolvers import reverse
from forms import MediaWidgetForm, MediaEmbedForm
from filebrowser.functions import handle_file_upload, convert_filename
from django.conf import settings
import os
from filebrowser.settings import ADMIN_THUMBNAIL
from cyclope.utils import generate_fb_version
from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from cyclope.apps.articles.models import Article
from cyclope.models import RelatedContent
from django.contrib.contenttypes.models import ContentType

# GET /pictures/new/article_id
def pictures_upload(request, article_id):
    """ Returns widget's inner HTML to be viewed through an iframe.
        This ensures bootstrap styles isolation."""
    #picture upload
    form = MediaWidgetForm()
    #TODO MediaWidgetSelectForm to select multiple pictures
    
    #picture selection
    pictures_list = Picture.objects.all().order_by('-creation_date')
    
    #admin picture refresh
    new_picture = {}
    delete_picture = False
    if request.session.has_key('refresh'):
        new_picture = {
            'picture_id': request.session.pop('refresh', False), 
            'picture_ct': ContentType.objects.get(model='picture').pk
        }
    elif request.session.has_key('delete'):
        #clean it from session
        delete_picture = request.session.pop('delete')

    return render(request, 'media_widget/pictures_upload.html', {
        'form': form, 
        'article_id': article_id,
        'pictures_list': pictures_list,
        'new_picture': new_picture,
        'delete_picture': delete_picture
    })

# POST /pictures/create/article_id
@require_POST
def pictures_create(request, article_id):
    if request.user.is_staff:
        form = MediaWidgetForm(request.POST, request.FILES)
        if form.is_valid():
            image = form.cleaned_data['image']
            #normalize file name
            image.name = convert_filename(image.name)
            #filesystem save
            path = os.path.join(settings.MEDIA_ROOT, Picture._meta.get_field_by_name("image")[0].directory)
            uploaded_path = handle_file_upload(path, image)
            #thumbnails
            generate_fb_version(uploaded_path, ADMIN_THUMBNAIL)
            #database save
            article = Article.objects.get(pk=article_id)
            picture = Picture(
                name = form.cleaned_data['name'] if form.cleaned_data['name']!='' else image.name,
                description = form.cleaned_data['description'],
                image = uploaded_path,
                user = article.user,
                author = article.author,
                source = article.source
            )
            picture.save()
            
            _associate_picture_to_article(article, picture)
            
            messages.success(request, 'Imagen cargada: '+image.name)
            request.session['refresh'] = picture.id
            
            #POST/Redirect/GET
            return redirect('pictures-new', article_id)
        else:
            #picture selection
            pictures_list = Picture.objects.all().order_by('-creation_date')
            return render(request, 'media_widget/pictures_upload.html', {
                'form': form, 
                'article_id': article_id,
                'pictures_list': pictures_list
            })
    else:
        return HttpResponseForbidden()
        
#POST /pictures/update/article_id
@require_POST
def pictures_update(request, article_id):
    if request.user.is_staff:
        article = Article.objects.get(pk=article_id)
        picture_id = int(request.POST.get('picture_id'))
        picture = Picture.objects.get(pk=picture_id)
        
        _associate_picture_to_article(article, picture)
        
        messages.success(request, 'Imagen seleccionada: '+picture.name)
        request.session['refresh'] = picture_id
        
        return redirect('pictures-new', article_id) # POST/Redirect/GET 
    else:
        return HttpResponseForbidden()

#GET /pictures/delete/article_id
def pictures_delete(request, article_id):
    if request.user.is_staff:
        article = Article.objects.get(pk=article_id)
        article.picture = None
        article.save()
        
        messages.warning(request, 'Imagen eliminada.')
        request.session['delete'] = True
        
        return redirect('pictures-new', article_id) # POST/Redirect/GET
    else:
        return HttpResponseForbidden()

#GET /embed/new
def embed_new(request):
    if request.user.is_staff:
        form = MediaEmbedForm()
        return render(request, 'media_widget/media_upload.html', {
            'form': form, 
        })
    else:
        return HttpResponseForbidden()

#TODO asociar automagicamente tipo de archivo por extension?
#POST /embed/create
@require_POST
def embed_create(request):
    if request.user.is_staff:
        form = MediaEmbedForm(request.POST, request.FILES)
        if form.is_valid():
            multimedia = form.cleaned_data['multimedia']
            media_type = form.cleaned_data['media_type']
            if _validate_file_extension(media_type, multimedia):
                klass = ContentType.objects.get(model=media_type).model_class()
                instance = klass() # generic instance of media model
                #filesystem save 
                path = os.path.join(
                    settings.MEDIA_ROOT, 
                    klass._meta.get_field_by_name(klass.media_file_field)[0].directory # TODO or just uploads?
                )
                uploaded_path = handle_file_upload(path, multimedia)
                #database save
                instance.name = form.cleaned_data['name'] if form.cleaned_data['name']!='' else multimedia.name
                instance.description = form.cleaned_data['description']
                instance.user = request.user
                setattr(instance, klass.media_file_field, uploaded_path)
                instance.save()
                #response
                return render(request, 'media_widget/media_upload.html', {
                    'form': form,
                    'file_url': instance.media_file,
                    'media_type': media_type
                })
            else:
                msg = _validation_error_message(multimedia, media_type)
                messages.error(request, msg)
                return render(request, 'media_widget/media_upload.html', {
                    'form': form,
                })
        else:
            return render(request, 'media_widget/media_upload.html', {
                'form': form, 
            })
    else:
        return HttpResponseForbidden()

#HELPERS
def _associate_picture_to_article(article, picture):
    """Helper method to DRY picture create and update"""
    #associate picture with current Article
    article.picture = picture
    article.save()
    #article as Picture's related content
    related = RelatedContent(
        self_object = picture,
        other_object = article
    )
    related.save()
    
#TODO what about validating this in javascript?
#TODO validate file extension too?
def _validate_file_extension(media_type, multimedia):
    """
    Validate uploaded file MIME type matches intended Content Type.
    Allowed MIME types are different than FileBrowser's because they're the ones allowed by HTML5.
    """
    if media_type == 'picture':
        top_level_mime, mime_type = tuple(multimedia.content_type.split('/'))
        return top_level_mime == 'image' # allow all image types TODO?
    else:
        if media_type == 'soundtrack':
            allowed_mime_types = ['audio/mpeg', 'audio/ogg', 'audio/wav']
        elif media_type == 'movieclip':
            allowed_mime_types = ['video/mp4', 'video/webm', 'video/ogg']
        elif media_type == 'document':
            allowed_mime_types = ['application/pdf']
        elif media_type == 'flashmovie':
            allowed_mime_types = ['x-shockwave-flash', 'x-flv']
        else:
            return False
        return multimedia.content_type in allowed_mime_types

def _validation_error_message(multimedia, media_type):
    type_name = {
        'picture': 'Image',
        'soundtrack': 'Audio',
        'movieclip': 'Video',
        'document': 'PDF',
        'flashmovie': 'Flash'
    }
    msg = multimedia.content_type+' is not a valid '+type_name[media_type]+' type!'
    return msg       
