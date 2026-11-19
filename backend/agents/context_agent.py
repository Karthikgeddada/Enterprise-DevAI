from typing import List, Dict, Any, Optional


class ContextAgent:
    """
    Retrieves relevant files and context for a task.
    Uses deterministic file search, not LLM.
    """

    def __init__(self, project_files: List[Dict[str, Any]], project_id: str, file_getter):
        """
        Args:
            project_files: List of file metadata dicts with 'path' keys.
            project_id: The project ID.
            file_getter: A callable(project_id, path) -> Optional[str] that returns file content.
        """
        self.project_files = project_files
        self.project_id = project_id
        self.get_file = file_getter

    def get_project_structure(self) -> str:
        """Return a text representation of the project file tree."""
        paths = sorted(f.get('path', '') for f in self.project_files)
        if not paths:
            return "(empty project)"
        lines = []
        for p in paths:
            depth = p.count('/')
            lines.append('  ' * depth + '- ' + p.split('/')[-1])
        return '\n'.join(lines)

    def get_relevant_files(self, task_description: str, files_affected: List[str]) -> List[Dict[str, str]]:
        """
        Retrieve files relevant to a task.
        Includes explicitly affected files plus keyword-matched files.
        """
        result = []
        seen = set()

        # First include explicitly mentioned files
        for path in files_affected:
            if path in seen:
                continue
            content = self.get_file(self.project_id, path)
            if content is not None:
                result.append({'path': path, 'content': content})
                seen.add(path)

        # Then find files by keyword matching on task description
        keywords = self._extract_keywords(task_description)
        for f in self.project_files:
            path = f.get('path', '')
            if path in seen:
                continue
            if any(kw in path.lower() for kw in keywords):
                content = self.get_file(self.project_id, path)
                if content is not None:
                    result.append({'path': path, 'content': content})
                    seen.add(path)

        return result

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from a task description."""
        # Simple keyword extraction - split on spaces, remove common words
        stop_words = {'the', 'a', 'an', 'to', 'in', 'on', 'at', 'for', 'of', 'and', 'or',
                      'is', 'are', 'was', 'were', 'be', 'been', 'add', 'update', 'modify',
                      'create', 'implement', 'fix', 'with', 'this', 'that', 'it', 'from'}
        words = text.lower().replace('.', ' ').replace(',', ' ').replace('/', ' ').split()
        return [w for w in words if len(w) > 2 and w not in stop_words]

    def build_context_string(self, task_description: str, files_affected: List[str]) -> str:
        """Build a context string for the LLM."""
        structure = self.get_project_structure()
        relevant = self.get_relevant_files(task_description, files_affected)

        parts = [f"Project Structure:\n{structure}\n"]
        if relevant:
            parts.append("Relevant Files:")
            for f in relevant:
                parts.append(f"\n--- {f['path']} ---\n{f['content']}\n")
        else:
            parts.append("No existing files match this task (new project).")

        return '\n'.join(parts)