-- flalac for Mac
--
-- Keeps this Mac's Music app (or iTunes) in step with the flalac mirror on the NAS: adds new
-- songs, removes deleted ones, follows renamed ones without losing their plays, refreshes
-- retagged ones, and syncs play counts with Jellyfin. flalac makes every decision; this script
-- only reads the library, sends it, and applies the answer.
--
-- Works with iTunes on Mac OS X 10.4 and later, and with the Music app. Save it from Script
-- Editor as an Application and run it whenever you like, for example after syncing an iPod.

property serverURL : "__SERVER__"
property mirrorFolder : ""

on run
	set appName to musicApp()
	if mirrorFolder is "" then
		display dialog "Before the first sync, open " & appName & " > Settings > Files and turn off \"Copy files to Music Media folder when adding\" and \"Keep Music Media folder organised\"." & return & return & "Then choose the flalac mirror folder (the ALAC folder on the NAS share)." buttons {"Cancel", "Choose Folder"} default button 2
		set mirrorFolder to POSIX path of (choose folder with prompt "Choose the flalac ALAC folder:")
	end if
	set root to mirrorFolder
	if root ends with "/" then set root to text 1 thru -2 of root
	try
		do shell script "test -d " & quoted form of root
	on error
		display dialog "The mirror folder is not reachable:" & return & root & return & return & "Connect the NAS share and run again." buttons {"OK"} default button 1 with icon stop
		return
	end try

	set totals to {0, 0, 0, 0, 0, 0}
	set notes to {}
	repeat with pass from 1 to 2
		try
			set reply to askServer(appName, root)
		on error message
			display dialog "Could not reach flalac at " & serverURL & ":" & return & message buttons {"OK"} default button 1 with icon stop
			return
		end try
		set done to applyAnswer(appName, reply)
		repeat with i from 1 to 6
			set item i of totals to (item i of totals) + (item i of done)
		end repeat
		set notes to item 7 of done
		-- Songs added in the first pass get their play counts paired in a second one
		if item 1 of done is 0 then exit repeat
	end repeat

	set summary to "Added " & item 1 of totals & ", removed " & item 2 of totals & ", followed " & item 3 of totals & " renamed, refreshed " & item 4 of totals & ", play counts set " & item 5 of totals & "."
	if item 6 of totals > 0 then set summary to summary & return & item 6 of totals & " changes failed; they are tried again next time."
	repeat with n in notes
		set summary to summary & return & (contents of n)
	end repeat
	display dialog summary buttons {"OK"} default button 1 with title "flalac"
end run

on musicApp()
	try
		do shell script "test -d /System/Applications/Music.app"
		return "Music"
	end try
	return "iTunes"
end musicApp

on readLibrary(appName)
	set code to "tell application \"" & appName & "\"
	with timeout of 600 seconds
		set lp to library playlist 1
		set pids to persistent ID of every file track of lp
		set counts to played count of every file track of lp
		set locs to location of every file track of lp
	end timeout
end tell
return {pids, counts, locs}"
	return run script code
end readLibrary

on askServer(appName, root)
	set {pids, counts, locs} to readLibrary(appName)
	set out to {"mac" & tab & (computer name of (system info)), "root" & tab & root}
	repeat with i from 1 to count of pids
		set p to ""
		try
			set p to POSIX path of (item i of locs)
		end try
		set end of out to "track" & tab & (item i of pids) & tab & (item i of counts) & tab & p
	end repeat
	set AppleScript's text item delimiters to (ASCII character 10)
	set body to out as text
	set AppleScript's text item delimiters to ""
	set requestFile to (POSIX path of (path to temporary items)) & "flalac-request.txt"
	set fh to open for access (POSIX file requestFile) with write permission
	try
		set eof fh to 0
		write body to fh as «class utf8»
	end try
	close access fh
	return do shell script "curl -sS -f --max-time 900 -H 'Content-Type: text/plain; charset=utf-8' --data-binary @" & quoted form of requestFile & " " & quoted form of (serverURL & "/api/mac-sync")
end askServer

on applyAnswer(appName, reply)
	set adds to {}
	set removes to {}
	set moves to {}
	set refreshes to {}
	set plays to {}
	set infos to {}
	set AppleScript's text item delimiters to tab
	repeat with ln in paragraphs of reply
		set parts to text items of (contents of ln)
		if (count of parts) > 1 then
			set k to item 1 of parts
			if k is "add" then
				set end of adds to (POSIX file (item 2 of parts))
			else if k is "remove" then
				set end of removes to item 2 of parts
			else if k is "move" then
				set end of moves to {item 2 of parts, POSIX file (item 3 of parts)}
			else if k is "refresh" then
				set end of refreshes to item 2 of parts
			else if k is "plays" then
				set end of plays to {item 2 of parts, (item 3 of parts) as integer}
			else if k is "info" then
				set end of infos to item 2 of parts
			end if
		end if
	end repeat
	set AppleScript's text item delimiters to ""

	set code to "on run {adds, removes, moves, refreshes, plays}
	set failed to 0
	set files_ to {}
	repeat with f in adds
		try
			set end of files_ to ((contents of f) as alias)
		on error
			set failed to failed + 1
		end try
	end repeat
	tell application \"" & appName & "\"
		with timeout of 3600 seconds
			set lp to library playlist 1
			repeat with p in removes
				try
					delete (first file track of lp whose persistent ID is (contents of p))
				on error
					set failed to failed + 1
				end try
			end repeat
			repeat with m in moves
				try
					set location of (first file track of lp whose persistent ID is (item 1 of m)) to (item 2 of m)
				on error
					set failed to failed + 1
				end try
			end repeat
			repeat with p in refreshes
				try
					refresh (first file track of lp whose persistent ID is (contents of p))
				on error
					set failed to failed + 1
				end try
			end repeat
			repeat with q in plays
				try
					set played count of (first file track of lp whose persistent ID is (item 1 of q)) to (item 2 of q)
				on error
					set failed to failed + 1
				end try
			end repeat
			if files_ is not {} then add files_ to lp
		end timeout
	end tell
	return failed
end run"
	set failed to run script code with parameters {adds, removes, moves, refreshes, plays}
	return {count of adds, count of removes, count of moves, count of refreshes, count of plays, failed, infos}
end applyAnswer
