# pylint: disable=unused-argument, no-self-use, avoid-list-comprehension
import difflib

from django.db.models import signals
from django.template.defaultfilters import safe
from django.utils.translation import ugettext_lazy as _

from simple_history.models import HistoricalRecords
from simple_history.admin import SimpleHistoryAdmin


def diff_objects(old_instance, new_instance, fields):
    """
        Diff two objects by examining the given fields and
        return a string.
    """
    full_diff = []

    for field in fields:
        field_diff = []
        old_value = getattr(old_instance, field.attname)
        new_value = getattr(new_instance, field.attname)
        for line in difflib.unified_diff(str(old_value).split('\n'),
                                         str(new_value).split('\n'),
                                         fromfile=field.attname,
                                         tofile=field.attname,
                                         lineterm=""):
            field_diff.append(line)
        full_diff.extend(field_diff)

    return "\n".join(full_diff)


def history_email_for(instance, title):
    """
        Generate the subject and email body that is sent via
        email notifications post update!
    """
    history = instance.history.latest()

    subject = _("UPDATE: %(model_name)s #%(pk)d - %(title)s") % {
        'model_name': instance.__class__.__name__,
        'pk': instance.pk,
        'title': title
    }

    body = _("""Updated on %(history_date)s
Updated by %(username)s

%(diff)s

For more information:
%(instance_url)s""") % {'history_date': history.history_date.strftime('%c'),
                        'username': getattr(history.history_user, 'username', ''),
                        'diff': history.history_change_reason,
                        'instance_url': instance.get_full_url()}
    return subject, body


class KiwiHistoricalRecords(HistoricalRecords):
    """
        This class will keep track of what fields were changed
        inside of the ``history_change_reason`` field. This gives us
        a crude changelog until upstream introduces their new interface.
    """

    # todo: HistoricalRecords doesn't seem to have a pre_save method
    # so not sure if this even works ATM
    def pre_save(self, instance, **kwargs):
        """
            Signal handlers don't have access to the previous version of
            an object so we have to load it from the database!
        """
        if kwargs.get('raw', False):
            return

        if instance.pk and hasattr(instance, 'history'):
            instance.previous = instance.__class__.objects.get(pk=instance.pk)

    def post_save(self, instance, created, using=None, **kwargs):
        """
            Calculate the changelog and call the inherited method to
            write the data into the database.
        """
        if kwargs.get('raw', False):
            return

        if hasattr(instance, 'previous'):
            instance.changeReason = diff_objects(instance.previous,
                                                 instance,
                                                 self.fields_included(instance))
        super().post_save(instance, created, using, **kwargs)

    def finalize(self, sender, **kwargs):
        """
            Connect the pre_save signal handler after calling the inherited method.
        """
        super().finalize(sender, **kwargs)
        signals.pre_save.connect(self.pre_save, sender=sender, weak=False)


class ReadOnlyHistoryAdmin(SimpleHistoryAdmin):
    """
        Custom history admin which shows all fields
        as read-only.
    """
    history_list_display = ['Diff']

    def Diff(self, obj):  # pylint: disable=invalid-name
        return safe('<pre>%s</pre>' % obj.history_change_reason)

    def get_readonly_fields(self, request, obj=None):
        # make all fields readonly
        readonly_fields = list(set(
            [field.name for field in self.opts.local_fields] +
            [field.name for field in self.opts.local_many_to_many]
        ))
        return readonly_fields
