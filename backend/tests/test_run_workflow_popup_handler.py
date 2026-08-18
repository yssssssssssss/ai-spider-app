from run_workflow import PopupHandler


class MissingElement:
    exists = False


class SafeDevice:
    def __call__(self, **selector):
        if selector.get("className") == "android.widget.ImageView":
            raise AssertionError("popup handler must not click arbitrary top icons")
        return MissingElement()

    def dump_hierarchy(self):
        raise AssertionError("popup handler must not dump an unused UI hierarchy")


def test_popup_handler_only_uses_explicit_close_selectors():
    assert PopupHandler(SafeDevice())._try_close_popup() is False
