import streamlit as st

try:
    from streamlit_ace import st_ace
    HAS_ACE = True
except ImportError:
    HAS_ACE = False


def render_code_editor(services):
    """Code editor with file content editing and save."""
    project_id = st.session_state.project_id
    current_file = st.session_state.current_file

    if not current_file:
        st.info("Select a file from the sidebar to edit.")
        return

    # Get file content
    content = services.project_service.get_file(project_id, current_file)
    if content is None:
        st.warning(f"File not found: {current_file}")
        return

    # File header with save indicator
    col1, col2 = st.columns([4, 1])
    with col1:
        st.subheader(f"📝 {current_file}")
    with col2:
        unsaved = st.session_state.unsaved_changes.get(current_file)
        if unsaved is not None and unsaved != content:
            st.warning("Unsaved changes", icon="⚠️")

    # Detect language
    lang = _detect_language(current_file)

    # Editor - use st.text_area for editing, st.code for read-only
    edit_mode = st.checkbox("Edit mode", value=False, key="edit_mode")

    if edit_mode:
        if HAS_ACE:
            edited = st_ace(
                value=content,
                language=lang,
                theme='monokai',
                keybinding='vscode',
                height=500,
                key=f"ace_{current_file}",
                auto_update=False,
            )
        else:
            edited = st.text_area(
                "File content",
                value=content,
                height=500,
                key=f"editor_{current_file}",
                label_visibility="collapsed",
            )
        if edited is not None:
            st.session_state.unsaved_changes[current_file] = edited

        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("💾 Save", key="save_file_btn", type="primary"):
                try:
                    services.project_service.save_file(project_id, current_file, edited, created_by="user")
                    st.session_state.unsaved_changes.pop(current_file, None)
                    st.success("File saved!")
                    st.rerun()
                except Exception as e:
                    st.warning(f"Save failed: {e}")
        def _cancel_edit(c=current_file):
            st.session_state.unsaved_changes.pop(c, None)
            st.session_state.edit_mode = False

        with col_cancel:
            st.button("↩️ Cancel", key="cancel_edit_btn", on_click=_cancel_edit)
    else:
        st.code(content, language=lang)
        def _enter_edit(c=current_file, ct=content):
            st.session_state.unsaved_changes[c] = ct
            st.session_state.edit_mode = True

        st.button("✏️ Edit", key="edit_btn", on_click=_enter_edit)


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.json': 'json',
        '.md': 'markdown',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.sql': 'sql',
        '.sh': 'bash',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return 'text'