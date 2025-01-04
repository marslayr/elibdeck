import datetime
from django.utils import timezone
import openpyxl
from allauth.core.internal.httpkit import redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.messages.context_processors import messages
from django.db.models.signals import post_migrate
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from books_catalog.forms import RenewBookForm
from .models import Book, Author, BookInstance, Genre, LibrarySettings, BorrowingHistory, Feedback
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import generic
from django.db.models import Q, Value, Avg
from django.db.models.functions import Concat
from .forms import FeedbackForm, LibrarySettingsForm, UpdateBookForm, AddBookForm
from django.contrib import messages


# from .models import get_library_settings

def home(request):
    """View function for home page"""

    # Generate counts of some of the main objects
    num_books = Book.objects.all().count()
    num_instances = BookInstance.objects.all().count()

    # Available books (status = 'a')
    num_instances_available = BookInstance.objects.filter(status__exact='a').count()

    num_authors = Author.objects.count()

    genres = Genre.objects.all()

    context = {
        'num_books': num_books,
        'num_instances': num_instances,
        'num_instances_available': num_instances_available,
        'num_authors': num_authors,
    }

    for genre in genres:
        context[f'{genre.name.lower()}_books'] = Book.objects.filter(genre=genre)

    return render(request, 'landing-page.html', context=context)


def upload_file(request):
    if "GET" == request.method:
        return render(request, 'books_catalog/upload.html', {})
    elif request.method == "POST":
        excel_file = request.FILES["excel_file"]
        wb = openpyxl.load_workbook(excel_file)

        # getting a particular sheet by name out of many sheets
        worksheet = wb["Sheet1"]
        print(worksheet)

        excel_data = list()
        # iterating over the rows and
        # getting value from each cell in row
        for row in worksheet.iter_rows():
            row_data = list()
            for cell in row:
                row_data.append(str(cell.value))
            excel_data.append(row_data)

        return render(request, 'books_catalog/upload.html', {"excel_data": excel_data})


@login_required
@permission_required('books_catalog.can_mark_returned', raise_exception=True)
def update_library_settings(request):
    # Get the existing library settings (singleton instance)
    library_settings, created = LibrarySettings.objects.get_or_create(pk=1)

    if request.method == 'POST':
        form = LibrarySettingsForm(request.POST, instance=library_settings)
        if form.is_valid():
            form.save()  # Save the updated settings
            return redirect('books_catalog:landing-page')  # Redirect to the home page after saving
    else:
        form = LibrarySettingsForm(instance=library_settings)  # Prepopulate form with current settings

    return render(request, 'books_catalog/update_library_settings.html', {'form': form})


class BookListView(generic.ListView):
    model = Book
    template_name = 'books_catalog/book_list.html'
    paginate_by = 10


class AuthorListView(generic.ListView):
    model = Author
    template_name = 'books_catalog/author_list.html'
    paginate_by = 10


class BookDetailView(generic.DetailView):
    model = Book
    template_name = 'books_catalog/book_detail.html'
    context_object_name = 'book'


class AuthorDetailView(generic.DetailView):
    model = Author
    template_name = 'books_catalog/author_detail.html'
    context_object_name = 'author'


class LoanedToUserListView(LoginRequiredMixin, generic.ListView):
    """Generic class-based view listing books on loan to current user."""
    model = BookInstance
    template_name = 'books_catalog/bookinstance_borrowed_user.html'
    context_object_name = 'bookinstance_list'
    paginate_by = 10

    def get_queryset(self):
        return (
            BookInstance.objects.filter(borrower=self.request.user)
            .filter(status__exact='o')
            .order_by('due_date')
        )


class AllLoanedListView(LoginRequiredMixin, generic.ListView):
    """Generic class-based view listing all books loaned by users."""
    model = BookInstance
    permission_required = 'catalog.can_mark_returned'
    template_name = 'books_catalog/bookinstance_borrowed_all.html'
    context_object_name = 'bookinstance_list_all'
    paginate_by = 10

    def get_queryset(self):
        return (
            BookInstance.objects.filter(status__exact='o')
            .order_by('due_date')
        )


@login_required
@permission_required('books_catalog.can_mark_returned', raise_exception=True)
def renew_book_librarian(request, pk):
    """Renew borrowed books, accessible to librarian."""
    book_instance = get_object_or_404(BookInstance, pk=pk)

    # If this is a POST request then process the Form data
    if request.method == 'POST':

        # Create a form instance and populate it with data from the request (binding):
        form = RenewBookForm(request.POST)

        # Check if the form is valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required (here we just write it to the model due_back field)
            book_instance.due_back = form.cleaned_data['renewal_date']
            book_instance.save()

            # redirect to a new URL:
            return HttpResponseRedirect(reverse('all-borrowed-books'))

    # If this is a GET (or any other method) create the default form.
    else:
        proposed_renewal_date = datetime.date.today() + datetime.timedelta(weeks=3)
        form = RenewBookForm(initial={'renewal_date': proposed_renewal_date})

    context = {
        'form': form,
        'book_instance': book_instance,
    }

    return render(request, 'books_catalog/renew_return_book_librarian.html', context)


@login_required
def borrow_book(request, pk):
    """Handles borrowing."""
    bookinst = get_object_or_404(BookInstance, id=pk)

    if bookinst.status == 'o':
        messages.error(request, 'This book has already been borrowed')
        return redirect('books_catalog:books')

    library_settings = LibrarySettings.objects.first()
    ISSUE_PERIOD = library_settings.ISSUE_PERIOD

    bookinst.book.borrowers.add(request.user)

    bookinst.status = 'o'
    bookinst.borrower = request.user
    bookinst.due_date = datetime.date.today() + datetime.timedelta(days=ISSUE_PERIOD)
    bookinst.save()

    messages.add_message(request, messages.SUCCESS,
                         f'You have successfully borrowed "{bookinst.book.title}, return on {bookinst.due_date}',
                         extra_tags='borrowed-tag')

    return redirect('books_catalog:profile-books')


@login_required
def return_book(request, pk):
    """Handles the return of a book."""
    # Get the BookInstance object using the ID passed in the URL
    bookinst = get_object_or_404(BookInstance, id=pk)
    # Check if the current user is the one who borrowed the book
    if bookinst.borrower != request.user:
        messages.error(request, 'You cannot return a book you did not borrow.')
        return redirect('books_catalog:books')  # Redirect to the book list or appropriate page

    # Check if the book is already returned (status is available)
    if bookinst.status == 'a':
        messages.error(request, 'This book has already been returned.')
        return redirect('books_catalog:books')

    # Mark the book as returned by updating status and borrower
    bookinst.status = 'a'
    bookinst.borrower = None
    bookinst.due_date = None  # Optional: remove due back date
    bookinst.save()

    # Provide a success message
    messages.success(request, f'You have successfully returned "{bookinst.book.title}".')

    return redirect('books_catalog:profile-books')  # Redirect to the book list or user's borrowed books page


# @login_required
# def history_borrowed_books(request):
#     borrow_records = BorrowingHistory.objects.filter(user=request.user).order_by('-return_date')
#
#     return render(request, 'books_catalog/bookinstance_borrowed_user_history.html', {'borrow_records':borrow_records})


class CatalogSearchView(generic.ListView):
    template_name = 'books_catalog/search_results.html'
    paginate_by = 10
    context_object_name = 'search_results'

    def get_queryset(self):
        query = self.request.GET.get('q', '')
        if not query:
            return []

        books = Book.objects.annotate(
            full_name=Concat('author__first_name', Value(' '), 'author__last_name')
        ).filter(
            Q(title__icontains=query) |
            Q(isbn__icontains=query) |
            Q(full_name__icontains=query) |
            Q(summary__icontains=query)
        ).distinct()

        return books

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        return context


@login_required
@permission_required('books_catalog.can_mark_returned', raise_exception=True)
def update_book(request, pk):
    # Get the book object by primary key (pk), if not found return 404
    book = get_object_or_404(Book, pk=pk)

    if request.method == 'POST':
        form = UpdateBookForm(request.POST, instance=book)  # Bind the form with the existing book instance
        if form.is_valid():
            form.save()  # Save the updated book details
            messages.success(request, 'Changes saved successfully!')
    else:
        form = UpdateBookForm(instance=book)  # Prepopulate the form with the current book details

    return render(request, 'books_catalog/update_book.html', {'form': form, 'book': book})


@login_required
@permission_required('books_catalog.can_mark_returned', raise_exception=True)
def add_book(request):
    if request.method == 'POST':
        form = AddBookForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Book added successfully!')
            return redirect('books_catalog:books')
    else:
        form = AddBookForm()

    return render(request, 'books_catalog/add_book.html', {'form': form})


# @login_required
# def submit_feedback(request, pk):
#     book = get_object_or_404(Book, id=pk)
#     if request.method == 'POST':
#         form = FeedbackForm(request.POST)
#         if form.is_valid():
#             feedback = form.save(commit=False)
#             feedback.book = book
#             feedback.save()
#     else:
#         form = FeedbackForm()
#
#     return render(request, 'books_catalog/feedback.html', {'form': form, 'book': book})

@login_required
def submit_feedback(request, pk):
    book = get_object_or_404(Book, pk=pk)  # Fetch the book by primary key

    if request.user not in book.borrowers.all():
        messages.error(request, "You can only leave feedback for books you have borrowed.")

    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.book = book
            feedback.save()
            messages.success(request, 'Thank you for your feedback!')
            form = FeedbackForm()

            return redirect('books_catalog:profile-books')
    else:
        form = FeedbackForm()

    return render(request, 'books_catalog/feedback.html', {'form': form, 'book': book})

@login_required
@permission_required('books_catalog.can_mark_returned', raise_exception=True)
def view_feedback(request, pk):
    book = get_object_or_404(Book, pk=pk)
    feedbacks = book.feedbacks.all()
    average_rating = feedbacks.aggregate(Avg('rating'))['rating__avg']

    return render(request, 'books_catalog/view_feedback.html', {
        'book': book,
        'feedbacks': feedbacks,
        'average_rating': average_rating
    })
