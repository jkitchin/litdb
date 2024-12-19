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
;; `litdb' is an ivy entry-point with selection on citation strings. The default
;; action inserts a link.
;; 
;; `litdb-fulltext' is an interactive function to do a full text search
;; 
;; `litdb-vsearch' is an interactive function to do a vector search
;; 
;; `litdb-gpt' is an interactive function to do a gpt query. This is quite slow
;; on my machine.
;;
;; You can update the filters with `litdb-update'. You need a premium OpenAlex key for that.
;; 
;; You should review your litdb periodically. `litdb-review' will prompt you for a time duration, and show you things that have been added since then. The duration could be something like "yesterday" or "last week" or a date.

(require 'hydra)
(require 'request)
(require 'counsel)
(require 'openalex)  			; in org-ref

;;; Code:

(defun litdb-get-db ()
  "Get the path to the litdb db.
If there is a dominating litdb.toml file we get the db from there.
Otherwise, we look for LITDB_ROOT as an environment variable."
  (let ((dir (or
	      (when-let (toml (locate-dominating-file default-directory "litdb.toml"))
		(file-name-directory toml))
	      (getenv "LITDB_ROOT"))))
    (if dir
	(f-join dir "litdb.libsql")
      (error "No litdb directory found."))))


(defmacro with-litdb (&rest body)
  "Run BODY in the directory where `litdb-db' is and with db defined."
  `(let* ((litdb-db (litdb-get-db))
	  (default-directory (file-name-directory litdb-db))
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


(defun litdb-about ()
  "Show a buffer with information about your litdb."
  (interactive)
  (let* ((default-directory (file-name-directory (litdb-get-db)))
	 (proc (start-process-shell-command "litdb about" "*litdb-about*"
					    "litdb about")))
    (pop-to-buffer (process-buffer proc))
    (org-mode)
    (goto-char (point-min))))

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
	(db (sqlite-open (litdb-get-db))))
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
  ("a" (litdb-open-in-openalex (litdb-path-at-point)) "OpenAlex" :column "Open")
  ("p" (let* ((candidates '())
	      (source (litdb-path-at-point))
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

	 (browse-url (completing-read "URL: " (remove nil candidates))))"pdf")
  
  ("i" litdb "Insert new link" :column "Insert")
  ("s" (litdb-insert-similar (litdb-path-at-point)) "Similar" :column "Insert")
  
  ("k" (kill-new (litdb-path-at-point)) "Copy source" :column "Copy")
  ("l" (kill-new (format "litdb:%s" (litdb-path-at-point))) "Copy link" :column "Copy")
  ("c" (litdb-copy-citation (litdb-path-at-point)) "Copy citation" :column "Copy")
  ("b" (litdb-copy-bibtex (litdb-path-at-point)) "Copy bibtex" :column "Copy")
  ("t" litdb-edit-tags-at-point "Edit tags" :column "Copy")
  
  ("gf" (let* ((default-directory (file-name-directory (litdb-get-db))))
	  (message "%s" (shell-command-to-string
			 (format "litdb add %s --references" (litdb-path-at-point)))))
   "Get references"  :column "Get")
  ("gc" (message "%s" (let* ((default-directory (file-name-directory (litdb-get-db))))
			(shell-command-to-string
			 (format "litdb add %s --citing" (litdb-path-at-point)))))
   "Get citing"  :column "Get")
  ("gr" (let* ((default-directory (file-name-directory (litdb-get-db))))
	  (message "%s" (shell-command-to-string
			 (format "litdb add %s --related" (litdb-path-at-point)))))
   "Get related" :column "Get"))


(defun litdb-edit-tags-at-point ()
  "Edit tags at point."
  (interactive)
  (litdb-edit-tags (litdb-path-at-point)))


(defun litdb-edit-tags (source)
  "Edit tags for SOURCE."
  (let* ((db (sqlite-open (litdb-get-db)))
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
  (let* ((default-directory (file-name-directory (litdb-get-db)))
	 (candidates (read (shell-command-to-string
			    (format "litdb similar -n 10 -e \"%s\"" source)))))
    (ivy-read "Choose: " candidates
	      :caller 'litdb
	      :action
	      '(1
		("o" (lambda (x)
		       ;; this is kind of dumb but the function takes a list,
		       ;; not a cons
		       (litdb-insert-candidate (list (car x)
						     (cdr x))))
		 "Insert in current link")
		("k" (lambda (x)
		       ;; this is kind of dumb but the function takes a list,
		       ;; not a cons
		       (kill-new (format "litdb:%s" (cdr x))))
		 "Copy link")
		("c" (lambda (x)
		       ;; this is kind of dumb but the function takes a list,
		       ;; not a cons
		       (let* ((db (sqlite-open (litdb-get-db)))
			      (source (cdr x))
			      (citation (caar (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?"
							     (list source)))))
			 (kill-new (format "%s %s" citation (format "litdb:%s" source)))))
		 "Copy citation + link")))))


(defun litdb-open-in-openalex (source)
  "Open source in OpenAlex."
  (interactive "sSource: ")
  (let* ((db (sqlite-open (litdb-get-db))))
    (browse-url
     (caar
      (sqlite-select db "select json_extract(extra, '$.id') from sources where source = ?"
		     (list source))))))


(defun litdb-copy-citation (source)
  "Copy a citation for SOURCE."
  (interactive "sSource: ")
  (let* ((db (sqlite-open (litdb-get-db))))
    (kill-new (caar (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?"
				   (list source))))))


(defun litdb-copy-bibtex (source)
  "Copy a bibtex for SOURCE."
  (interactive "sSource: ")
  (let* ((db (sqlite-open (litdb-get-db))))
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
  (let* ((attributes (file-attributes (litdb-get-db)))
	 (db-mod-time (nth 5 attributes))
	 (db (sqlite-open (litdb-get-db)))
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


(defun litdb-get-pdf (source)
  "Try to open a PDF for SOURCE."
  (let* ((candidates '())
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
					   (list source))))))
    
    ;; try with unpaywall
    (cl-loop for loc in (plist-get data :oa_locations)
	     do
	     (setq candidates (append candidates (list (plist-get loc :url_for_pdf)))))

    (browse-url (completing-read "URL: " (remove nil candidates)))))

(defun litdb ()
  "Entry point for litdb.
Default action inserts a link"
  (interactive)
  (let* ((db (sqlite-open (litdb-get-db)))
	 (candidates (litdb-candidates)))
    
    (ivy-read "choose: " candidates
	      :caller 'litdb
	      :action
	      '(1
		("o" litdb-insert-candidate "Insert link")
		("c" (lambda (x) (kill-new (nth 0 x))) "Copy citation")
		("b" (lambda (x) (litdb-copy-bibtex (nth 1 x))) "Copy bibtex")
		("l" (lambda (x) (kill-new (format "litdb:%s" (nth 1 x)))) "Copy link")
		("p" (lambda (x) (litdb-get-pdf (nth 1 x))) "Open pdf")
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
	 (db (sqlite-open (litdb-get-db)))
	 (results (sqlite-select db "select snippet(fulltext, 1, '', '', '', 64),source
    from fulltext
    where text match ? order by rank limit ?" (list query N))))
    (ivy-read "choose: " results
	      :caller 'litdb
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
		       (let* ((db (sqlite-open (litdb-get-db)))
			      (bibtex (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list (nth 1 x))))))
			 
			 (kill-new bibtex)))
		 "Insert bibtex")
		("c" (lambda (x)
		       "Copy citation string."
		       (let* ((db (sqlite-open (litdb-get-db)))
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
  (let* ((default-directory (file-name-directory (litdb-get-db)))
	 (N (or N 5))
	 (candidates (read (shell-command-to-string
			    (format "litdb vsearch -n %s -e \"%s\"" N query)))))
    
    (ivy-read "Choose: " candidates
	      :caller 'litdb
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
		       (let* ((db (sqlite-open (litdb-get-db)))
			      (bibtex (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list (cdr x))))))
			 
			 (kill-new bibtex)))
		 "Copy bibtex")
		("c" (lambda (x)
		       "Copy bibtex string."
		       (let* ((db (sqlite-open (litdb-get-db)))
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
  (let* ((proc (async-start-process "litdb-gpt" "litdb"
				    (lambda (proc)
				      (switch-to-buffer (process-buffer proc))
				      (org-mode)
				      (goto-char (point-min)))
				    "gpt" query)))

    (set-process-sentinel proc (lambda (process event)
				 "Sentinel to keep the buffer alive after PROCESS finishes."
				 (when (memq (process-status process) '(exit signal))
				   (let ((buffer (process-buffer process)))
				     (when (buffer-live-p buffer)
				       (with-current-buffer buffer
					 (org-mode)
					 (goto-char (point-min))))))))
    (switch-to-buffer-other-frame (process-buffer proc))))


;; * review functions

(defcustom litdb-speed-commands
  '(;; delete org heading
    ("d" . (progn
	     (org-mark-element)
	     (cl--set-buffer-substring (region-beginning)
				       (region-end)
				       "")
	     (litdb-review-header)))
    
    ;; tag entry
    ("t" . (litdb-edit-tags (org-entry-get (point) "SOURCE")))

    ;; open in OpenAlex
    ("x" . (progn
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
    ("P" . (litdb-get-pdf (org-entry-get (point) "SOURCE")))

    ;; insert in litdb
    ("a" . (let ((source (org-entry-get (point) "SOURCE")))
	     (shell-command (format "litdb add \"%s\"" source))
	     (message "added %s" source)))
    
    ;; get related, citing, references
    ("r" (lambda ()
	   (let* ((default-directory (file-name-directory (litdb-get-db)))
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
	   (let* ((default-directory (file-name-directory (litdb-get-db)))
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
	   (let* ((default-directory (file-name-directory (litdb-get-db)))
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
  (when (and (string-prefix-p "*litdb" (buffer-name))
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


(defun litdb-update ()
  "Update the filters in litdb.
Show new updated results in a buffer: *litdb-update*."
  (interactive)
  (let* ((process-environment (cons "COLUMNS=10000" process-environment))
	 (proc (start-process-shell-command "litdb-update" "*litdb-update*" "litdb update-filters -s")))
    (set-process-sentinel proc (lambda (process event)
				 "Sentinel to keep the buffer alive after PROCESS finishes."
				 (when (memq (process-status process) '(exit signal))
				   (let ((buffer (process-buffer process)))
				     (when (buffer-live-p buffer)
				       (with-current-buffer buffer
					 (org-mode)
					 (litdb-review-header)
					 (goto-char (point-min))))))))
    (switch-to-buffer-other-frame (process-buffer proc))))


(defun litdb-review (since)
  "Open a buffer to review articles SINCE a date.
This runs asynchronously, and a review buffer appears in another frame."
  (interactive (list (read-string "Since: " "one week ago")))
  (let* ((process-environment (cons "COLUMNS=10000" process-environment))
	 (proc (start-process-shell-command
		"litdb-review" "*litdb-review*" 
		(format "litdb review -s %s" since))))
    (set-process-sentinel proc (lambda (process event)
				 "Sentinel to keep the buffer alive after PROCESS finishes."
				 (when (memq (process-status process) '(exit signal))
				   (let ((buffer (process-buffer process)))
				     (when (buffer-live-p buffer)
				       (with-current-buffer buffer
					 (org-mode)
					 (litdb-review-header)
					 (goto-char (point-min))))))))
    (switch-to-buffer-other-frame (process-buffer proc))))


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
  (let ((default-directory (file-name-directory (litdb-get-db)))
	(db (sqlite-open (litdb-get-db))))
    
    (shell-command (format "litdb add \"%s\"" doi))
    (insert 
     (caar
      (sqlite-select db "select json_extract(extra, '$.citation') from sources where source = ?" (list doi))))
    (insert (format " litdb:%s\n\n" doi))))


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
  (litdb-review-header))


(defun litdb-openalex (filter &optional cursor)
"Run a query with FILTER in OpenAlex.
Results are shown in an org-buffer.

CURSOR is optional, and used to make a link to the next page of results.

The idea in this function is to use speed keys to add items.

Example filters:
fulltext.search:yeast,publication_year:>2020
"
(interactive "sFilter: ")

(when (null cursor)
  (setq cursor "*"))

(let* ((url "https://api.openalex.org/works")
       (parser (lambda ()
		 "Parse the response from json to elisp."
		 (let ((json-array-type 'list)
		       (json-object-type 'plist)
		       (json-key-type 'keyword)
		       (json-false nil)
		       (json-encoding-pretty-print nil))
		   (json-read))))
       (req (request url
	      :sync t
	      :parser parser
	      :params `(("cursor" . ,cursor)
			("filter" . ,filter))))
       (data (request-response-data req))
       (metadata (plist-get data :meta))
       (results (plist-get data :results))
       (next-page (format "[[elisp:(litdb-openalex \"%s\" \"%s\")][Next page]]"
			  filter
			  (plist-get metadata :next_cursor)))
       (buf (get-buffer-create "*litdb-openalex*")))
  
  (with-current-buffer buf
    (erase-buffer)
    (org-mode)
    (insert (s-format "#+title: OpenAlex search: ${filter} (${count} results)

${next-page}

Speed keys:
| d | delete heading    |
| a | open in Open Alex |
| r | get related items |
| f | get references    |
| c | get citing papers |
| P | get pdf           |

"
		      'aget
		      `(("filter" . ,filter)
			("next-page" . ,next-page)
			("count" . ,(plist-get metadata :count)))))

    (insert
     (cl-loop for result in results concat 
	      (s-format "* ${title}
:PROPERTIES:
:JOURNAL: ${primary_location.source.display_name}
:AUTHOR: ${authors}
:YEAR: ${publication_year}
:OPENALEX: ${id}
:SOURCE: ${ids.doi}
:REFERENCE_COUNT: ${referenced_works_count}
:CITED_BY_COUNT: ${cited_by_count}
:END:

${abstract}

" (lambda (key data)
    (or (cdr (assoc key data)) ""))

`(("title" . ,(oa--title result))
  ("primary_location.source.display_name" . ,(oa-get result "primary_location.source.display_name"))
  ("authors" . ,(oa--authors result))
  ("publication_year" . ,(oa-get result "publication_year"))
  ("id" . ,(oa-get result "id"))
  ("ids.doi" . ,(oa-get result "ids.doi"))
  ("cited_by_count" . ,(oa-get result "cited_by_count"))
  ("referenced_works_count" . ,(oa-get result "referenced_works_count"))
  ("abstract" . ,(oa--abstract result))))))

    (insert (format "* %s" next-page))
    
    (goto-char (point-min)))
  (pop-to-buffer buf)
  (org-next-visible-heading 1)))


;; * extract entries to bibtex

(defun litdb-generate-bibtex (bibtex-file)
  "Parse the org-buffer, collect litdb links, and create a bibtex file from them.

Note it is not certain all the bibtex entries are correct and valid.
Notably, the DOI or OpenAlex id is used as a key, and almost certainly
some of these are invalid."
  (interactive "fBibtex file: ")
  
  ;; get all the paths from litdb links
  (let* ((db (sqlite-open (litdb-get-db)))
	 (sources (org-element-map (org-element-parse-buffer) 'link
		    (lambda (link)
		      (let ((plist (nth 1 link))
			    (keys '()))
			(when (string= "litdb" (plist-get plist ':type))
			  (setq keys (append
				      keys
				      (split-string
				       (org-element-property :path link)
				       ","))))))))
	 ;; use the stored bibtex entries. It is not clear this is the best
	 ;; thing to do, but so far it works. It would be faster than trying to
	 ;; get them all from crossref.
	 (bibtex-entries (cl-loop for source in (flatten-list sources)
				  collect
				  (caar (sqlite-select db "select json_extract(extra, '$.bibtex') from sources where source = ?" (list source))))))

    (when (and (file-exists-p bibtex-file)
	       (not (y-or-n-p (format "%s exists. Clobber it?" bibtex-file))))
      (error "%s exists." bibtex-file))
    
    (with-temp-file bibtex-file
      (insert (string-join bibtex-entries "\n")))))


(provide 'litdb)

;;; litdb.el ends here
