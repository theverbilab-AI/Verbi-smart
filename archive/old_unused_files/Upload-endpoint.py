@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload single or multiple files with parallel processing"""
    
    if 'file' not in request.files and 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    # Single file
    if 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Create call record
        call_id = f"CALL-{secrets.token_hex(4).upper()}"
        new_call = {
            "id": call_id,
            "filename": filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "queued",
            "customer_id": request.form.get('customer_id', 'UNKNOWN'),
            "loan_id": request.form.get('loan_id', 'UNKNOWN'),
            "agent_id": request.form.get('agent_id', 1)
        }
        calls_data.insert(0, new_call)
        
        # Process async
        process_call_async(call_id, filepath, calls_data, lambda cid, updates: update_call(cid, updates))
        
        return jsonify({"message": "File uploaded", "call": new_call}), 201
    
    # Multiple files (batch)
    files = request.files.getlist('files')
    uploaded_calls = []
    
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            call_id = f"CALL-{secrets.token_hex(4).upper()}"
            new_call = {
                "id": call_id,
                "filename": filename,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "status": "queued",
                "audio_path": filepath
            }
            calls_data.insert(0, new_call)
            uploaded_calls.append({"id": call_id, "audio": filepath})
    
    # Process all in parallel
    process_calls_parallel(uploaded_calls, lambda cid, updates: update_call(cid, updates))
    
    return jsonify({
        "message": f"Uploaded {len(uploaded_calls)} files",
        "calls": [c["id"] for c in uploaded_calls]
    }), 201

def update_call(call_id, updates):
    """Update call record thread-safe"""
    for call in calls_data:
        if call['id'] == call_id:
            call.update(updates)
            break