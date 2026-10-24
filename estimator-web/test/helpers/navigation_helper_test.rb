require "test_helper"

class NavigationHelperTest < ActionView::TestCase
  include NavigationHelper

  def with_controller(path, action: "index")
    singleton_class.send(:define_method, :controller_path) { path }
    singleton_class.send(:define_method, :action_name) { action }
  end

  test "maps each controller to its section" do
    with_controller("home")
    assert_equal :home, current_section

    with_controller("estimations", action: "new")
    assert_equal :new_estimation, current_section

    with_controller("estimations", action: "index")
    assert_equal :history, current_section

    with_controller("rag/chunking_comparisons")
    assert_equal :rag, current_section

    with_controller("ai_settings", action: "show")
    assert_equal :settings, current_section
  end

  test "nav_link marks only the active section" do
    with_controller("rag/chunking_comparisons")

    active = nav_link("Chunking Lab", "/rag/chunking_comparisons", :rag)
    inactive = nav_link("Ajustes", "/ai_settings", :settings)

    assert_includes active, 'class="active"'
    assert_includes active, 'aria-current="page"'
    refute_includes inactive, "active"
    refute_includes inactive, "aria-current"
  end
end
