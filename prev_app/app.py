import gradio as gr

def greet(name):
    return f"Hello, {name}!"

def add(a, b):
    return a + b

with gr.Blocks() as demo:
    gr.Markdown("# Simple Gradio App")
    
    with gr.Tab("Greeting"):
        name_input = gr.Textbox(label="Enter your name")
        greet_output = gr.Textbox(label="Greeting")
        greet_btn = gr.Button("Greet")
        greet_btn.click(greet, inputs=name_input, outputs=greet_output)
    
    with gr.Tab("Calculator"):
        a_input = gr.Number(label="Number A")
        b_input = gr.Number(label="Number B")
        calc_output = gr.Number(label="Result")
        add_btn = gr.Button("Add")
        add_btn.click(add, inputs=[a_input, b_input], outputs=calc_output)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7864)
