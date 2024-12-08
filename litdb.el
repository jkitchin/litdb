;;; litdb.el --- litdb and emacs

;;; Commentary:
;; 
;; We define a new link: litdb
;; 
;; litdb:https://doi.org/10.1002/cssc.202200362
;;
;; These links are functional, and can export to \cite commands in LaTeX, and
;; you can extract bibtex entries with `litdb-generate-bibtex'.
;;
;; You have to define where your db is in `litdb-db' for now.
;;
;; `litdb' is an ivy entry-point with selection on citation strings. The default
;; action inserts a link.
;; 
;; `litdb-fulltext' is an interactive function to do a full text search
;; 
;; `litdb-vsearch' is an interactive function to do a vector search
;; 
;; `litdb-gpt' is an interactive function to do a gpt query. This is quite slow
;; on my machine.

(require 'hydra)

;;; Code:

(defcustom litdb-db nil
  "Path to your litdb.")


(defmacro with-litdb (&rest body)
  "Run BODY in the directory where `litdb-db' is and with db defined."
  `(let ((default-directory (file-name-directory litdb-db))
	 (db (sqlite-open litdb-db)))
     ,@body))


(defun litdb-tags ()
  "Show entries with a tag."
  (interactive)
  (let* ((tags (with-litdb
		(sqlite-select db "select tag, rowid from tags")))
	 (tag (ivy-read "Tag: " tags))
	 (tag-id (nth 1 (assoc tag tags)))
	 (entries (with-litdb
		   (sqlite-select db "select json_extract(sources.extra, '$.citation'),sources.source
from sources
inner join source_tag on sources.rowid = source_tag.source_id
inner join tags on tags.rowid = source_tag.tag_id
where source_tag.tag_id = ?" (list tag-id)))))

    (ivy-read "Entry: " entries)))

;; * litdb link definition

(defface litdb-link-face
  `((t (:inherit org-link
                 :foreground "dark green")))
  "Color for litdb links.")


(org-link-set-parameters
 "litdb"
 :face 'litdb-link-face
 :activate-func #'litdb-activate
 :follow #'litdb-follow
 :help-echo #'litdb-tooltip
 :export #'litdb-export)


(defun litdb-export (path _desc backend)
  "Barest export function for PATH.
BACKEND is a symbol but only 'latex is supported, and only the simplest
cite command."
  (cond
   ((eq backend 'latex)
    (format "\\cite{%s}" path))

   (t
    (error "%s not supported yet." backend))))


(defun litdb-activate (start end path _bracketp)
  "Activation function for a litdb link
START and END are the bounds. PATH could be a comma-separated list."
  (let ((substrings (split-string path ","))
	(db (sqlite-open litdb-db)))
    (goto-char start)
    (cl-loop for path in substrings
	     do
	     (search-forward path end)
	     (put-text-property (match-beginning 0)
				(match-end 0)
				'litdb-key
				path)

	     (put-text-property (match-beginning 0)
				(match-end 0)
				'litdb
				(caar (sqlite-select db "select json_extract(extra, '$.citation'), source from sources where source = ?" (list path)))))))

(defun litdb-path-at-point ()
  "Return the path at point. Set in `litdb-activate'."
  (get-text-property (point) 'litdb-key))


(defhydra litdb-follow (:color blue :hint nil)
  "litdb actions
"
  ("o" (browse-url (litdb-path-at-point)) "Open" :column "Open")
  ("a" (litdb-openalex (litdb-path-at-point)) "OpenAlex" :column "Open")
  
  ("il" litdb "Insert new link" :column "Insert")
  ("is" (litdb-insert-similar (litdb-path-at-point)) "Insert similar" :column "Insert")
  
  ("k" (kill-new (litdb-path-at-point)) "Copy key" :column "Copy")
  ("c" (litdb-copy-citation (litdb-path-at-point)) "Copy citation" :column "Copy")
  ("b" (litdb-copy-bibtex (litdb-path-at-point)) "Copy bibtex" :column "Copy")
  ("t" litdb-edit-tags-at-point "Edit tags" :column "Copy")
  
  ("gf" (let* ((default-directory (file-name-directory litdb-db)))
	  (message "%s" (shell-command-to-string
			 (format "litdb add %s --references" (litdb-path-at-point)))))
   "Get references"  :column "Get")
  ("gc" (message "%s" (let* ((default-directory (file-name-directory litdb-db)))
			(shell-command-to-string
			 (format "litdb add %s --citing" (litdb-path-at-point)))))
   "Get citing"  :column "Get")
  ("gr" (let* ((default-directory (file-name-directory litdb-db)))
	  (message "%s" (shell-command-to-string
			 (format "litdb add %s --related" (litdb-path-at-point)))))
   "Get related" :column "Get"))


(defun litdb-edit-tags-at-point ()
  "Edit tags at point."
  (interactive)
  (litdb-edit-tags (litdb-path-at-point)))


(defun litdb-edit-tags (source)
  "Edit tags for SOURCE."
  (let* ((db (sqlite-open litdb-db))
	 (tags (cl-loop for (tag) in  (sqlite-select db "select tag from tags")
			collect tag))
	 (source-id (caar (sqlite-select db "select rowid from sources where source = ?" (list source))))
	 (current-tags (cl-loop for (tag) in  (sqlite-select db "select tags.tag from tags inner join source_tag on tags.rowid=source_tag.tag_id where source_tag.source_id=?" (list source-id))
				collect tag))
	 (new-tags (string-split (read-string "Tags (space separated): " (string-join current-tags " ")) " ")))

    ;; delete old tags
    (cl-loop for tag in current-tags do
	     (let ((tag-id (caar (sqlite-select db "select rowid from tags where tag=?" (list tag)))))
	       (sqlite-execute db "delete from source_tag where source_tag.source_id=? and source_tag.tag_id=?"
	      		       (list source-id tag-id))))

    ;; add new tags
    (cl-loop for tag in new-tags do
	     (progn
	       (sqlite-execute db "insert or ignore into tags(tag) values (?)" (list tag))
	       (let ((tag-id (caar (sqlite-select db "select rowid from tags where tag=?" (list tag)))))
		 (sqlite-execute db "insert into source_tag(source_id, tag_id) values (?, ?)"
				 (list source-id tag-id)))))))


(defun litdb-insert-similar (source)
  "Insert new entry similar to SOURCE by vector similarity.
This function is kind of slow because it uses the cli."
  (let* ((default-directory (file-name-directory litdb-db))
	 (candidates (read (shell-command-to-string
			    (format "litdb similar -n 10 -e \"%s\"" source)))))
    (ivy-read "Choose: " candidates
	      :action
	      '(1
		("o" (lambda (x)
		       ;; this is kind of dumb but the function takes a list,
		       ;; not a cons
		       (litdb-insert-candidate (list (car x)
						     (cdr x))))
		 "Insert")))))


(defun litdb-openalex (source)
  "Open source in OpenAlex."
  (interactive "sSource: ")
  (let* ((db (sqlite-open litdb-db)))
    (browse-url
     (caar
      (sqlite-select db "select json_extract(extra, '$.id') from sources where source = ?"
		     (list source))))))


(defun litdb-copy-citation (source)
  "Copy a citation for SOURCE."
  (interactive "sSource: ")
  (let* ((db (sqlite-open litdb-db)))
    (kill-new (caar (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?"
				   (list source))))))


(defun litdb-copy-bibtex (source)
  "Copy a bibtex for SOURCE."
  (interactive "sSource: ")
  (let* ((db (sqlite-open litdb-db)))
    (kill-new (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?"
				   (list source))))))

(defun litdb-follow (_path)
  "Hydra for litdb-follow function"
  (interactive)
  (litdb-follow/body))


(defun litdb-tooltip (win _obj position)
  "Get the litdb tooltip at POSITION.
We use the citation from litdb. That might not exist for every entry.
Argument WIN The window."
  (interactive)
  (with-current-buffer (window-buffer win)
    (get-text-property position 'litdb)))


;; * Insert litdb links

(defvar litdb-insert-cache '(nil . nil)
  "Cache to use on candidates.
The car is a timestamp for when the cache was created. The cdr are the
candidates.")


(defun litdb-candidates ()
  "Return the candidates to insert a link.
Use a cache if possible, and generate if not."
  (let* ((attributes (file-attributes litdb-db))
	 (db-mod-time (nth 5 attributes))
	 (db (sqlite-open litdb-db))
	 candidates)
    (if (and (not (null (car litdb-insert-cache)))
	     (time-less-p db-mod-time (car litdb-insert-cache)))
	(cdr litdb-insert-cache)
      ;; generate cache
      (setq candidates (sqlite-select db "select json_extract(extra, '$.citation'), source from sources")
	    litdb-insert-cache (cons (current-time) candidates))
      candidates)))


(defun litdb-insert-candidate (x)
  "Insert a link with X.
X is a candidate (citation source) as a list." 
  (cond
   ;; on a source in a link. add to end
   ((get-text-property (point) 'litdb)
    ;; go to end, insert source
    (goto-char (or (next-single-property-change (point) 'litdb) (line-end-position)))
    (insert (format ",%s" (nth 1 x))))

   ;; at the end of a link, one character past. this won't work for bracketed links
   ((get-text-property (- (point) 1) 'litdb)
    (insert (format ",%s" (nth 1 x))))

   ;; on the link type
   ((eq (get-text-property (point) 'face) 'litdb-link-face)
    (search-forward ":")
    (insert (format "%s," (nth 1 x))))

   ;; all other conditions I think we just insert a link.
   (t
    (insert (format "litdb:%s" (nth 1 x))))))


(defun litdb ()
  "Entry point for litdb.
Default action inserts a link"
  (interactive)
  (let* ((db (sqlite-open litdb-db))
	 (candidates (litdb-candidates)))
    
    (ivy-read "choose: " candidates
	      :caller 'litdb
	      :action
	      '(1
		("o" litdb-insert-candidate "Insert link")
		("c" (lambda (x) (kill-new (nth 0 x))) "Copy citation")
		("u" (lambda (x) (browse-url (nth 1 x))) "Open url")))))


(defun litdb-display-transformer (candidate)
  "Prepare bib entry CANDIDATE for display.
This transformer allows org syntax in the candidate strings and wraps it to a nice length."
  (let* ((width (- (frame-width) 2))
	 (shr-width width)
	 (idx (get-text-property 1 'idx candidate))
	 (entry (cdr (nth idx (ivy-state-collection ivy-last)))))
    
    (with-temp-buffer 
      (insert
       (s-concat 
	(if (s-starts-with-p ivy-mark-prefix candidate)
	    ivy-mark-prefix "")
	candidate))
      
      (shr-render-region (point-min) (point-max))
      (string-trim-right (buffer-string)))))

(ivy-configure 'litdb :display-transformer-fn #'litdb-display-transformer)

;; * Interactive functions to search / query
;;
;; These are not super fast functions. Maybe they could be faster if I was
;; running a local server. Right now they go through a shell command.

(defun litdb-fulltext (query N)
  "Do a fulltext search on QUERY. Defaults to a selected region, or prompts you.
N is a numeric prefix arg to set the number of entries to return. Default is 5.

Default action is insert link. Some other actions include:
- open the source
- insert bibtex
- insert citation"
  (interactive (list
		(if (region-active-p)
		    (buffer-substring-no-properties (region-beginning) (region-end))
		  (read-string "Query: "))
		current-prefix-arg))
  (let* ((N (or current-prefix-arg 5))
	 (db (sqlite-open litdb-db))
	 (results (sqlite-select db "select snippet(fulltext, 1, '', '', '', 64),source
    from fulltext
    where text match ? order by rank limit ?" (list query N))))
    (ivy-read "choose: " results
	      :action
	      '(1
		("o" (lambda (x)
		       "Insert a link."
		       (message "insert: %S" x)
		       (insert (format "litdb:%s" (nth 1 x))))
		 "insert link")
		("u" (lambda (x)
		       "Open the source. Assumes a url."
		       (message "open: %S" x)
		       (browse-url (nth 1 x)))
		 "Open source")
		("b" (lambda (x)
		       "Copy bibtex string."
		       (let* ((db (sqlite-open litdb-db))
			      (bibtex (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list (nth 1 x))))))
			 
			 (kill-new bibtex)))
		 "Insert bibtex")
		("c" (lambda (x)
		       "Copy citation string."
		       (let* ((db (sqlite-open litdb-db))
			      (citation (caar (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?" (list (nth 1 x))))))
			 
			 (kill-new citation)))
		 "Copy citation")))))


(defun litdb-vsearch (query N)
  "Do a vector search on litdb with QUERY. Defaults to selected region, or prompts you.
N is a numeric prefix arg for number of candidates to include. Default is 5.

This is not a fast function. It goes through the litdb cli command."
  (interactive (list
		(if (region-active-p)
		    (buffer-substring-no-properties (region-beginning) (region-end))
		  (read-string "Query: "))
		current-prefix-arg))
  (let* ((default-directory (file-name-directory litdb-db))
	 (N (or N 5))
	 (candidates (read (shell-command-to-string
			    (format "litdb vsearch -n %s -e \"%s\"" N query)))))
    
    (ivy-read "Choose: " candidates
	      :action
	      '(1
		("o" (lambda (x)
		       (insert (format "litdb:%s" (cdr x)))))
		("u" (lambda (x)
		       "Open the source. Assumes a url."
		       (message "open: %S" x)
		       (browse-url (cdr x)))
		 "Open source")
		("b" (lambda (x)
		       "Copy bibtex string."
		       (let* ((db (sqlite-open litdb-db))
			      (bibtex (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list (cdr x))))))
			 
			 (kill-new bibtex)))
		 "Copy bibtex")
		("c" (lambda (x)
		       "Copy bibtex string."
		       (let* ((db (sqlite-open litdb-db))
			      (citation (caar (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?" (list (cdr x))))))
			 
			 (kill-new citation)))
		 "Copy citation")))))


(defun litdb-gpt (query)
  "Run litdb gpt on the QUERY.

This is done in an async process because it goes through the litdb cli
command, and it is slow (it can be minutes to generate depending on what
else the computer is going). I don't have GPU acceleration on this. It
is here as a proof of concept. With the async process you can keep
working while it generates."
  (interactive (list (if (region-active-p)
			 (buffer-substring-no-properties (region-beginning) (region-end))
		       (read-string "Query: "))))
  (let* ((default-directory (file-name-directory litdb-db))
	 (proc (async-start-process "litdb-gpt" "litdb"
				    (lambda (proc)
				      (switch-to-buffer (process-buffer proc))
				      (org-mode)
				      (goto-char (point-min)))
				    "gpt" query)))
    (pop-to-buffer (process-buffer proc))))


;; * review functions

(defcustom litdb-speed-commands
  '(;; delete org heading
    ("d" . (progn
	     (org-mark-element)
	     (cl--set-buffer-substring (region-beginning)
				       (region-end)
				       "")
	     (litdb-review-header)))
    ;; TODO
    ;; tag entry
    ("t" . (litdb-edit-tags (org-entry-get (point) "SOURCE")))

    ;; open in OpenAlex
    ("a" . (progn
	     (with-litdb
	      (browse-url
	       (caar
		(sqlite-select db
			       "select json_extract(extra, '$.id') from sources where source = ?"
			       (list (org-entry-get (point) "SOURCE"))))))))
    ;; delete entry from database
    ("D" . (progn
	     (with-litdb
	      (sqlite-execute "delete from sources where source = ?"
			      (list (org-entry-get (point) "SOURCE"))))
	     (org-mark-element)
	     (cl--set-buffer-substring (region-beginning)
				       (region-end)
				       "")
	     (litdb-review-header)))
    
    ;; refile the heading to somewhere
    ("r" . litdb-refile-to-project)

    ;; get / open pdf
    ("P" . (let* ((candidates '())
		  (source (org-entry-get (point) "SOURCE"))
		  (unpaywall (format "https://api.unpaywall.org/v2/%s" source))
		  (parser (lambda ()
			    "Parse the response from json to elisp."
			    (let ((json-array-type 'list)
				  (json-object-type 'plist)
				  (json-key-type 'keyword)
				  (json-false nil)
				  (json-encoding-pretty-print nil))
			      (json-read))))
		  (resp (request unpaywall
			  :sync t :parser parser
			  :params '(("email" . "jkitchin@cmu.edu"))))
		  (data (request-response-data resp)))
	     
	     (setq candidates (append
			       candidates
			       (with-litdb
				(car (sqlite-select db
						    "select json_extract(extra, '$.primary_location.pdf_url') from sources where source = ?"
						    (list (org-entry-get (point) "SOURCE")))))))
	     
	     ;; try with unpaywall
	     (cl-loop for loc in (plist-get data :oa_locations)
		      do
		      (setq candidates (append candidates (list (plist-get loc :url_for_pdf)))))

	     (browse-url (completing-read "URL: " (remove nil candidates)))))
    
    ;; get related, citing, references
    ("r" (lambda ()
	   (let* ((default-directory (file-name-directory litdb-db))
		  (source (org-entry-get (point) "SOURCE"))
		  (proc (async-start-process "litdb" "litdb"
					     (lambda (proc)
					       (switch-to-buffer (process-buffer proc))
					       (org-mode)
					       (goto-char (point-min)))
					     "add" source "--related" "-v")))
	     (pop-to-buffer (process-buffer proc))
	     (insert (format "Adding related for %s\n" source)))))
    ("f" (lambda ()
	   (let* ((default-directory (file-name-directory litdb-db))
		  (source (org-entry-get (point) "SOURCE"))
		  (proc (async-start-process "litdb" "litdb"
					     (lambda (proc)
					       (switch-to-buffer (process-buffer proc))
					       (org-mode)
					       (goto-char (point-min)))
					     "add" source "--references" "-v")))
	     (pop-to-buffer (process-buffer proc))
	     (insert (format "Adding references for %s\n" source)))))
    ("c" (lambda ()
	   (let* ((default-directory (file-name-directory litdb-db))
		  (source (org-entry-get (point) "SOURCE"))
		  (proc (async-start-process "litdb" "litdb"
					     (lambda (proc)
					       (switch-to-buffer (process-buffer proc))
					       (org-mode)
					       (goto-char (point-min)))
					     "add" source "--citing" "-v")))
	     (pop-to-buffer (process-buffer proc))
	     (insert (format "Adding citing papers for %s\n" source))))))
  "List of speed commands for litdb.")

(defun litdb-speed-keys (keys)
  "Find the command to run for KEYS."
  (when (and (string-prefix-p "*litdb review" (buffer-name))
	     (bolp)
	     (looking-at org-outline-regexp))
    (cdr (assoc keys litdb-speed-commands))))

(add-hook 'org-speed-command-hook 'litdb-speed-keys)


(defun litdb-review-header ()
  "Add/update a header with number of entries."
  (setq header-line-format
	(format "%s entries - Click to update" (count-matches org-heading-regexp (point-min) (point-max)))))


(local-set-key [header-line down-mouse-1]
	       `(lambda ()
		  (interactive)
		  (litdb-review-header)))


(defun litdb-review (since)
  "Open a buffer to review articles SINCE a date.
This runs asynchronously, and a review buffer appears in another frame."
  (interactive (list (read-string "Since: " "one week ago")))
  (async-start
   ;; What to do in the child process
   `(lambda ()
      (let ((default-directory (file-name-directory ,litdb-db)))
	(shell-command "litdb update-filters")
	(shell-command-to-string (format "litdb review -s \"%s\"" ,since))))

   ;; What to do when it finishes
   `(lambda (result)
      (message "Something got done!")
      (let ((buf (get-buffer-create (format "*litdb review - %s*" ,since))))
	(with-current-buffer buf
	  (insert result))
	(switch-to-buffer-other-frame buf)
	(goto-char (point-min))
	(org-mode)
	(litdb-review-header)))))


(defun litdb-insert-article (doi)
  "Add DOI to litdb, and insert an org item for review."
  ;; TODO: make a heading? tag the entry as unread or something?
  (interactive (list (cond
		      ((region-active-p)
		       (buffer-substring (region-beginning) (region-end)))
		      ((progn
			 (let ((current-kill (ignore-errors (current-kill 0 t))))
			   (when (and (stringp current-kill)
				      (or
				       (string-prefix-p "https://doi.org" current-kill)
				       (string-prefix-p "http://dx.doi.org" current-kill)
				       (string-prefix-p "10." current-kill)))
			     current-kill))))
		      (t
		       (read-string "DOI: ")))))
  (let ((default-directory (file-name-directory litdb-db))
	(db (sqlite-open litdb-db)))
    
    (shell-command (format "litdb add \"%s\"" doi))
    (insert 
     (caar
      (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?" (list doi))))
    (insert (format " litdb:%s" doi))))


(defun litdb-refile-to-project (project)
  "Refile current heading to a heading in the current project.
If PROJECT is non-nil (prefix arg) or you are not in a project,
you will be prompted to pick one."
  (interactive "P")
  (let* ((default-directory (cond
			     ((or project (not (projectile-project-p)))
			      (ivy-read "Project: " projectile-known-projects))
			     (t
			      (projectile-project-p))))
	 (org-files (-filter (lambda (f)
			       (and
				(f-ext? f "org")
				(not (s-contains? "#" f))))
			     (projectile-current-project-files)))
	 (headlines (cl-loop for file in org-files
			     append
			     (let ((hl '()))
			       
			       (when (file-exists-p file)
				 (with-temp-buffer
				   (insert-file-contents file)
				   ;; (org-mode)
				   ;; (font-lock-ensure)
				   (goto-char (point-min))
				   (while (re-search-forward org-heading-regexp nil t)
				     (cl-pushnew
				      (list
				       (format "%-80s (%s)"
					       (match-string 0)
					       (file-name-nondirectory file))
				       :file file
				       :headline (match-string 0)
				       :position (match-beginning 0))
				      hl))))
			       hl)))
	 (selection (ivy-read "Heading: " headlines))
	 (candidate (cdr (assoc selection headlines)))
	 (rfloc (list
		 (plist-get candidate :headline)
		 (plist-get candidate :file)
		 nil
		 (plist-get candidate :position))))
    (org-refile nil nil rfloc))
  (litdb-feed-header))

;; * extract entries to bibtex

(defun litdb-generate-bibtex (bibtex-file)
  "Parse the org-buffer, collect litdb links, and create a bibtex file from them.

Note it is not certain all the bibtex entries are correct and valid.
Notably, the DOI or OpenAlex id is used as a key, and almost certainly
some of these are invalid."
  (interactive "fBibtex file: ")

  ;; get all the paths
  (let* ((db (sqlite-open litdb-db))
	 (sources (org-element-map (org-element-parse-buffer) 'link
		    (lambda (link)
		      (let ((plist (nth 1 link))
			    (keys '()))
			(when (string= "litdb" (plist-get plist ':type))
			  (setq keys (append keys (org-element-property :path link))))))))
	 ;; look up bibtex entries. In theory this is ok, but the entries don't
	 ;; have the right key to match right now.
	 (bibtex-entries (cl-loop for source in sources
				  collect
				  (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list source))))))

    (with-temp-file bibtex-file
      (insert (string-join bibtex-entries "\n")))))


(provide 'litdb)

;;; litdb.el ends here
